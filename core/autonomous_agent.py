"""
Autonomous multi-step task orchestration for SAM's "overnight agent" mode.

This is the engine behind requests like "build me a CNN image classifier
project with a report and PPT by tomorrow morning" — it breaks a goal into
a checkpointed step list, executes steps one at a time against SAM's
existing tools (dev_agent, browser_control, file_controller, code_helper),
and survives interruption: progress is saved to disk after every single
step, so if SAM (or your machine) restarts mid-task, it resumes exactly
where it left off instead of starting over.

WHAT THIS DOES NOT DO: run anything itself. It's an orchestrator — actual
work (writing code, training a model, browsing a page) happens via the
`step_executor` callable you pass to AutonomousAgent.run(), which is where
main.py wires in the real tool functions. This separation is what makes
the orchestration logic (checkpointing, resume, retry) testable without
needing real tools, real hardware, or real time — see the test suite for
exactly that.

HONEST LIMITS:
  - This does not make GPU-hours appear. If a step is "train a CNN for
    50 epochs," that step takes as long as it takes on your hardware —
    the agent doesn't speed that up, it just doesn't lose progress if
    something interrupts it mid-run (checkpointing is step-level, not
    inside a single long-running step).
  - Planning quality depends entirely on the brain backend (Gemini/GPT-5)
    producing a sensible step list — this module doesn't validate that
    the plan is *correct*, only that each step either succeeds, fails,
    or gets retried predictably.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Callable, Optional


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR       = get_base_dir()
TASKS_DIR      = BASE_DIR / "memory" / "autonomous_tasks"
MAX_RETRIES    = 2   # per-step retry budget before marking it permanently failed
MAX_PLAN_STEPS = 12
_ALLOWED_TOOLS = {"dev_agent", "browser_control", "file_controller", "code_helper", "web_search", "computer_control"}
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE    = "done"
STATUS_FAILED  = "failed"

_PLAN_SYSTEM_PROMPT = """You are a project-planning assistant. Break the user's goal into a
concrete, ordered list of steps SAM can execute autonomously. Each step must use exactly one
of these tools: dev_agent (build project files, write code, run verification), browser_control
(research, download things, look things up), file_controller (organize/move/manage files),
code_helper (code review/refactoring), web_search (find APIs/docs).

Respond with ONLY a JSON array, no other text, no markdown fences. Each item:
{"description": "short human-readable description", "tool": "dev_agent|browser_control|file_controller|code_helper|web_search", "params": {...tool-specific parameters...}}

Keep it to 4-10 steps. Order matters — later steps can depend on earlier ones having run."""


class AutonomousAgent:
    """
    One autonomous task instance. Each has a unique task_id and a JSON
    checkpoint file at memory/autonomous_tasks/<task_id>.json holding the
    goal, the step list, and each step's status/result — that file is the
    entire resume mechanism.
    """

    def __init__(self, goal: str, task_id: Optional[str] = None):
        self.goal = goal
        self.task_id = task_id or uuid.uuid4().hex[:12]
        self.steps: list[dict] = []
        self.created_at = time.time()
        TASKS_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def checkpoint_path(self) -> Path:
        return TASKS_DIR / f"{self.task_id}.json"

    # ── Persistence ──────────────────────────────────────────────────────

    def save_checkpoint(self) -> None:
        data = {
            "task_id":    self.task_id,
            "goal":       self.goal,
            "created_at": self.created_at,
            "steps":      self.steps,
        }
        # Atomic replace prevents a power loss/crash from leaving a half-written
        # checkpoint that makes an overnight job impossible to resume.
        TASKS_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{self.task_id}.", suffix=".tmp", dir=TASKS_DIR)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                json.dump(data, tmp, indent=2, ensure_ascii=False)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_name, self.checkpoint_path)
            try:
                self.checkpoint_path.chmod(0o600)
            except OSError:
                pass
        finally:
            try:
                Path(tmp_name).unlink(missing_ok=True)
            except OSError:
                pass

    @classmethod
    def load(cls, task_id: str) -> "AutonomousAgent":
        task_id = str(task_id or "").strip()
        if not _TASK_ID_RE.fullmatch(task_id):
            raise ValueError("Invalid autonomous task id.")
        path = TASKS_DIR / f"{task_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        agent = cls(goal=data["goal"], task_id=data["task_id"])
        agent.created_at = data.get("created_at", time.time())
        agent.steps = data.get("steps", [])
        return agent

    @classmethod
    def list_tasks(cls) -> list[dict]:
        """Returns {task_id, goal, status, progress} for every checkpointed task,
        newest first — used by the status-check tool and the Task Queue UI."""
        if not TASKS_DIR.exists():
            return []
        out = []
        for f in sorted(TASKS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                steps = data.get("steps", [])
                done = sum(1 for s in steps if s.get("status") == STATUS_DONE)
                failed = sum(1 for s in steps if s.get("status") == STATUS_FAILED)
                if not steps:
                    status = "planning"
                elif done == len(steps):
                    status = "complete"
                elif done + failed == len(steps):
                    status = "finished_with_failures"
                else:
                    status = "in_progress"
                out.append({
                    "task_id": data["task_id"], "goal": data["goal"],
                    "status": status, "progress": f"{done}/{len(steps)}",
                    "failed": failed,
                })
            except Exception:
                continue
        return out

    # ── Planning ─────────────────────────────────────────────────────────

    def plan(self, brain_call: Callable[..., dict]) -> None:
        """
        Uses brain_call(prompt, system, task_type) — i.e. brain_router.call_brain
        — to turn self.goal into a step list. Raises if the response isn't
        parseable JSON; caller decides what to do (this never silently
        produces a broken plan).
        """
        result = brain_call(self.goal, system=_PLAN_SYSTEM_PROMPT, task_type="complex")
        content = result["content"] if isinstance(result, dict) else result
        steps = _parse_step_list(content)
        if not steps:
            raise ValueError(f"Planner returned no usable steps. Raw response: {content[:300]}")
        if len(steps) > MAX_PLAN_STEPS:
            raise ValueError(f"Planner returned {len(steps)} steps; maximum is {MAX_PLAN_STEPS}.")

        cleaned = []
        for index, s in enumerate(steps, 1):
            if not isinstance(s, dict):
                raise ValueError(f"Planner step {index} is not an object.")
            tool = str(s.get("tool", "")).strip()
            description = str(s.get("description", "")).strip()
            params = s.get("params", {})
            if tool not in _ALLOWED_TOOLS:
                raise ValueError(f"Planner step {index} uses unsupported tool: {tool!r}")
            if not description:
                raise ValueError(f"Planner step {index} has no description.")
            if not isinstance(params, dict):
                raise ValueError(f"Planner step {index} params must be an object.")
            cleaned.append({
                "description": description[:200],
                "tool":        tool,
                "params":      params,
                "status":      STATUS_PENDING,
                "result":      "",
                "retries":     0,
            })
        self.steps = cleaned
        self.save_checkpoint()

    # ── Execution ────────────────────────────────────────────────────────

    def run(
        self,
        step_executor: Callable[[dict], str],
        on_progress: Optional[Callable[[int, int, dict], None]] = None,
        stop_check: Optional[Callable[[], bool]] = None,
    ) -> dict:
        """
        Executes all pending steps in order. Steps already in a terminal
        state from a prior run are skipped — this is the resume mechanism,
        and it's automatic: just call run() again with the same task_id and
        it picks up where it left off.

        step_executor(step) -> str: runs one step, returns a result string,
            raises on failure. This is where main.py wires in real tools —
            kept as an injected callable so this engine is testable without
            them.
        on_progress(done_count, total_count, step): called after every step
            (success or final failure) — wire to UI updates.
        stop_check() -> bool: if provided and returns True, execution pauses
            before the next step (checkpoint already saved) instead of
            continuing — used for graceful cancellation.

        Returns a summary dict: {"completed", "failed", "skipped", "total"}.
        """
        total = len(self.steps)
        for i, step in enumerate(self.steps):
            # Skip steps that already reached a TERMINAL state in a previous
            # run. DONE is obvious; FAILED matters just as much — a step that
            # already exhausted its retry budget must NOT be retried again on
            # resume, or a permanently-broken step would loop forever across
            # restarts (each fresh run would reset its retry counter and try
            # again). Use retry_failed_steps() to deliberately re-arm them.
            if step["status"] in (STATUS_DONE, STATUS_FAILED):
                continue

            if stop_check and stop_check():
                break

            step["status"] = STATUS_RUNNING
            self.save_checkpoint()

            while True:
                try:
                    result = step_executor(step)
                    step["status"] = STATUS_DONE
                    step["result"] = str(result)[:2000]
                    break
                except Exception as e:
                    step["retries"] += 1
                    if step["retries"] > MAX_RETRIES:
                        step["status"] = STATUS_FAILED
                        step["result"] = f"Failed after {step['retries']} attempts: {e}"
                        break
                    # else: retry immediately. Note the checkpoint still marks
                    # this step RUNNING, so a crash mid-retry leaves it
                    # non-terminal and a resumed run will pick it up again.

            self.save_checkpoint()
            if on_progress:
                on_progress(i + 1, total, step)

        done    = sum(1 for s in self.steps if s["status"] == STATUS_DONE)
        failed  = sum(1 for s in self.steps if s["status"] == STATUS_FAILED)
        skipped = total - done - failed
        return {"completed": done, "failed": failed, "skipped": skipped, "total": total}

    def retry_failed_steps(self) -> int:
        """
        Re-arms permanently-failed steps so the next run() attempts them
        again (resets status to PENDING and clears their retry counter).
        Deliberate opt-in — run() alone will never retry a failed step, by
        design. Returns how many steps were re-armed.
        """
        count = 0
        for step in self.steps:
            if step["status"] == STATUS_FAILED:
                step["status"] = STATUS_PENDING
                step["retries"] = 0
                step["result"] = ""
                count += 1
        if count:
            self.save_checkpoint()
        return count


def _parse_step_list(content: str) -> list[dict]:
    """Extracts a JSON array from the planner's response, tolerating markdown
    fences or leading/trailing prose the model might add despite instructions."""
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    try:
        parsed = json.loads(content)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass
    m = re.search(r"\[.*\]", content, re.DOTALL)
    if m:
        try:
            parsed = json.loads(m.group(0))
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    return []
