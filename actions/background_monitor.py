"""
background_monitor.py — SAM Overnight Project & Background Task Monitor
Inspects status, progress, milestones, and deliverables for autonomous overnight agents.
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional

from core.autonomous_agent import AutonomousAgent, STATUS_DONE, STATUS_FAILED, STATUS_RUNNING


def background_monitor(parameters: dict = None, **kwargs) -> str:
    params = parameters if isinstance(parameters, dict) else {}
    task_id = (params.get("task_id") or params.get("id") or "").strip()
    
    tasks = AutonomousAgent.list_tasks()
    if not tasks:
        return (
            "No active background projects are currently registered, sir. "
            "You can say 'build me an overnight project <description>' to start one anytime."
        )
    
    # If specific task requested or only 1 task exists
    target_id = task_id or (tasks[0]["task_id"] if len(tasks) == 1 else "")
    
    if target_id:
        try:
            agent = AutonomousAgent.load(target_id)
            created_str = datetime.datetime.fromtimestamp(agent.created_at).strftime("%Y-%m-%d %H:%M")
            total = len(agent.steps)
            done = sum(1 for s in agent.steps if s.get("status") == STATUS_DONE)
            failed = sum(1 for s in agent.steps if s.get("status") == STATUS_FAILED)
            running = sum(1 for s in agent.steps if s.get("status") == STATUS_RUNNING)
            
            lines = [
                f"[STATUS] Background Project (Task ID: {agent.task_id}):",
                f"  Goal: {agent.goal}",
                f"  Started: {created_str}",
                f"  Overall Progress: {done}/{total} steps completed ({done*100//total if total else 0}%)",
            ]
            
            if agent.steps:
                lines.append("\n[PLAN] Step Checklist:")
                for i, step in enumerate(agent.steps, 1):
                    st = step.get("status", "pending")
                    tag = "[DONE]" if st == STATUS_DONE else ("[RUNNING]" if st == STATUS_RUNNING else ("[FAILED]" if st == STATUS_FAILED else "[PENDING]"))
                    desc = step.get("description", "")
                    tool = step.get("tool", "")
                    line = f"  {tag} Step {i}: {desc} [{tool}] — {st.upper()}"
                    if st == STATUS_DONE and step.get("result"):
                        snippet = step.get("result", "").strip().splitlines()[0][:80]
                        line += f" ({snippet})"
                    lines.append(line)
                    
            if done == total and total > 0:
                lines.append("\n[SUCCESS] All deliverables for this project are 100% complete, sir!")
            elif running:
                lines.append("\n[ACTIVE] Project is actively executing right now.")
            else:
                lines.append("\n[WAITING] Background worker is active and proceeding.")
                
            return "\n".join(lines)
        except Exception as e:
            return f"Error loading task {target_id}: {e}"
            
    # Multiple tasks summary
    lines = [f"Found {len(tasks)} background project(s), sir:\n"]
    for t in tasks:
        tag = "[COMPLETE]" if t.get("status") == "complete" else ("[FAIL]" if t.get("failed", 0) > 0 else "[RUNNING]")
        lines.append(
            f"{tag} ID: {t['task_id']} | Goal: '{t['goal'][:45]}...' | "
            f"Progress: {t['progress']} | Status: {t['status'].upper()}"
        )
    lines.append("\nSay 'project status for <id>' to inspect full step details.")
    return "\n".join(lines)


# Alias for autonomous_status
def autonomous_status(parameters: dict = None, **kwargs) -> str:
    return background_monitor(parameters, **kwargs)
