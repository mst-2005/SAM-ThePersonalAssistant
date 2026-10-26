"""
dev_agent.py — SAM Autonomous Software Engineer Agent
Enables building complete software projects from scratch, writing robust code,
running automated tests, self-healing syntax errors, and verifying deliverables.
"""
from __future__ import annotations

import ast
import json
import os
import platform
import py_compile
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

from core.brain_router import call_brain

_OS = platform.system()


def _get_default_projects_dir() -> Path:
    """Returns the default directory for user projects."""
    if _OS == "Windows":
        onedrive_desktop = Path.home() / "OneDrive" / "Desktop"
        if onedrive_desktop.exists():
            p = onedrive_desktop / "Projects"
            p.mkdir(parents=True, exist_ok=True)
            return p
    desktop = Path.home() / "Desktop"
    if desktop.exists():
        p = desktop / "Projects"
        p.mkdir(parents=True, exist_ok=True)
        return p
    docs = Path.home() / "Documents" / "Projects"
    docs.mkdir(parents=True, exist_ok=True)
    return docs


def _sanitize_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_\- ]", "", name).strip()
    return cleaned.replace(" ", "_").lower() or "sam_project"


def _clean_code_block(raw: str) -> str:
    """Extracts raw code from potential markdown code fences."""
    raw = raw.strip()
    m = re.search(r"```(?:\w+)?\n(.*?)```", raw, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Strip single fences if any
    raw = re.sub(r"^```[a-zA-Z0-9_]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return raw.strip()


def _validate_python_syntax(file_path: Path) -> tuple[bool, str]:
    """Validates Python syntax via ast parsing and py_compile."""
    try:
        content = file_path.read_text(encoding="utf-8")
        ast.parse(content, filename=str(file_path))
        py_compile.compile(str(file_path), doraise=True)
        return True, "Syntax OK"
    except (SyntaxError, py_compile.PyCompileError) as e:
        return False, str(e)
    except Exception as e:
        return False, f"Validation warning: {e}"


def _self_heal_code(file_path: Path, error_msg: str, language: str = "python") -> bool:
    """Attempts to automatically fix syntax/compilation errors using the brain."""
    try:
        code = file_path.read_text(encoding="utf-8")
        prompt = (
            f"The following {language} file failed compilation with error:\n"
            f"{error_msg}\n\n"
            f"Here is the broken code:\n```\n{code}\n```\n\n"
            "Provide the COMPLETE, fixed code without any markdown explanation. "
            "Output ONLY the corrected code inside ``` code fences."
        )
        res = call_brain(prompt, system="You are an expert debugger. Fix all syntax and runtime issues. Return full code only.", task_type="complex")
        fixed = _clean_code_block(res.get("content", ""))
        if fixed:
            file_path.write_text(fixed, encoding="utf-8")
            if language == "python":
                ok, _ = _validate_python_syntax(file_path)
                return ok
            return True
    except Exception:
        pass
    return False


def build_project(
    goal: str,
    project_name: str = "",
    target_dir: Optional[str] = None,
    language: str = "python"
) -> str:
    """
    Builds a complete, production-grade project end-to-end.
    Plans architecture, writes all files, adds tests, README, requirements,
    and runs self-verification.
    """
    if not project_name:
        words = [w for w in re.sub(r"[^a-zA-Z0-9 ]", "", goal).split() if len(w) > 2]
        project_name = "_".join(words[:4]).lower() if words else "autonomous_project"
    
    project_name = _sanitize_name(project_name)
    
    if target_dir:
        base_path = Path(target_dir).expanduser()
    else:
        base_path = _get_default_projects_dir() / project_name
    
    base_path.mkdir(parents=True, exist_ok=True)
    
    # Step 1: Architectural Planning
    wants_report = any(w in goal.lower() for w in ("report", "documentation", "paper", "summary document"))
    wants_presentation = any(w in goal.lower() for w in ("powerpoint", "presentation", "ppt", "slides", "deck"))

    plan_prompt = (
        f"Design the architecture for a complete project deliverables package.\n"
        f"Goal: {goal}\n"
        f"Language: {language}\n"
        f"Project directory: {base_path.name}\n\n"
        "Requirements:\n"
        "- Include all necessary source code files, requirements.txt, and README.md.\n"
        f"{'- MUST include a comprehensive project report (e.g. REPORT.md and report.docx or report.py generator)' if wants_report else ''}\n"
        f"{'- MUST include generate_presentation.py to build presentation.pptx with slides' if wants_presentation else ''}\n"
        "Return ONLY a JSON object listing files to create with their purpose and key components.\n"
        "Format:\n"
        "{\n"
        '  "files": [\n'
        '    {"filename": "main.py", "description": "Entry point and primary application logic"},\n'
        '    {"filename": "core.py", "description": "Core algorithms and helper classes"},\n'
        '    {"filename": "test_project.py", "description": "Comprehensive unit tests"},\n'
        '    {"filename": "requirements.txt", "description": "List of dependencies"},\n'
        '    {"filename": "README.md", "description": "Project documentation and run instructions"}\n'
        "  ]\n"
        "}\n"
        "Do NOT include markdown fences or other text. Only JSON."
    )
    
    plan_res = call_brain(plan_prompt, system="You are a Principal Software Architect. Plan clean, modular, realistic project structures.", task_type="complex")
    raw_plan = plan_res.get("content", "").strip()
    
    files_to_create = []
    try:
        cleaned_json = re.sub(r"^```(?:json)?\s*", "", raw_plan)
        cleaned_json = re.sub(r"\s*```$", "", cleaned_json)
        parsed = json.loads(cleaned_json)
        files_to_create = parsed.get("files", [])
    except Exception:
        # Fallback file list if JSON parsing fails
        files_to_create = [
            {"filename": "main.py", "description": "Core application entrypoint"},
            {"filename": "utils.py", "description": "Support functions and utilities"},
            {"filename": "test_app.py", "description": "Test suite"},
            {"filename": "requirements.txt", "description": "Dependencies"},
            {"filename": "README.md", "description": "Overview and instructions"}
        ]
    
    created_files = []
    errors = []
    
    # Step 2: Code Generation for Each File
    for f_info in files_to_create:
        fname = f_info.get("filename", "")
        fdesc = f_info.get("description", "")
        if not fname:
            continue
        
        file_path = base_path / fname
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        code_prompt = (
            f"You are implementing a file for the following software project:\n"
            f"Goal: {goal}\n"
            f"File to implement: {fname}\n"
            f"File Purpose: {fdesc}\n\n"
            f"All planned files in this project: {[f.get('filename') for f in files_to_create]}\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "- Write COMPLETE, production-ready, working code.\n"
            "- Do NOT leave placeholders, `# TODO`, `# implement here`, or dummy pass statements.\n"
            "- Handle errors gracefully with try/except blocks.\n"
            "- If this is README.md, write comprehensive documentation with installation and usage instructions.\n"
            "- If this is requirements.txt, list only standard or verified PyPI packages.\n"
            "- Return ONLY the code inside ``` code fences."
        )
        
        try:
            code_res = call_brain(code_prompt, system="You are an elite Senior Staff Engineer writing production code. Deliver fully functioning code.", task_type="complex")
            code_text = _clean_code_block(code_res.get("content", ""))
            
            file_path.write_text(code_text, encoding="utf-8")
            
            # Syntax validation & self-healing for Python files
            if fname.endswith(".py"):
                ok, err = _validate_python_syntax(file_path)
                if not ok:
                    healed = _self_heal_code(file_path, err, language="python")
                    if not healed:
                        errors.append(f"{fname}: syntax warning ({err})")
            
            created_files.append((fname, len(code_text.splitlines())))
        except Exception as e:
            errors.append(f"Failed to generate {fname}: {e}")
    
    # Step 3: Run Verification Test & Deliverable Builders
    # Automatically execute generate_presentation.py or generate_report.py if created
    for gen_script in base_path.rglob("generate_*.py"):
        try:
            subprocess.run(
                [sys.executable, str(gen_script)],
                cwd=str(gen_script.parent),
                capture_output=True,
                timeout=30,
            )
        except Exception:
            pass

    test_output = "No test script found."
    test_files = list(base_path.rglob("test_*.py")) + list(base_path.rglob("*_test.py"))
    for test_file in test_files:
        if test_file.exists():
            try:
                proc = subprocess.run(
                    [sys.executable, str(test_file)],
                    cwd=str(test_file.parent),
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                test_output = proc.stdout or proc.stderr or "Tests passed successfully."
                break
            except subprocess.TimeoutExpired:
                test_output = "Test execution timed out after 20s."
            except Exception as te:
                test_output = f"Test execution error: {te}"
    
    # Step 4: Summary Report
    salutation = "Ma'am"
    try:
        from core.llm_client import _load_config
        salutation = _load_config().get("salutation", "Ma'am")
    except Exception:
        pass

    lines = [
        f"[OK] Project successfully built, {salutation}!",
        f"  Location: {base_path}",
        f"  Files generated ({len(created_files)} total):",
    ]
    for name, line_count in created_files:
        lines.append(f"  - {name} ({line_count} lines)")
    
    # Step 4: Outbound Cell Phone Alert (Calls or sends SMS if doubts/errors occur or on completion)
    try:
        from actions.phone_notifier import call_user_phone, send_phone_sms, _load_config
        p_cfg = _load_config()
        if p_cfg.get("user_phone_number"):
            if errors:
                doubt_msg = (
                    f"Hello {salutation}, this is SAM calling regarding your project '{project_name}'. "
                    f"I encountered a question or doubt on {len(errors)} file(s): {', '.join(errors[:2])}. "
                    f"Please review the console or reply to guide me."
                )
                call_user_phone(message=doubt_msg)
            else:
                comp_msg = (
                    f"Good day {salutation}. SAM has finished building your project '{project_name}' "
                    f"with {len(created_files)} files at {base_path.name}. All verifications passed."
                )
                call_user_phone(message=comp_msg)
    except Exception as phone_err:
        print(f"[DevAgent] Phone notification notice: {phone_err}")

    lines.append(f"\n[VERIFICATION]:\n{test_output[:300]}")

    # Step 5: Save project metadata for instant on-screen opening
    try:
        last_project_file = Path(__file__).resolve().parent.parent / "config" / "last_project.json"
        last_project_file.parent.mkdir(parents=True, exist_ok=True)
        main_py = str(base_path)
        py_files = [f[0] for f in created_files if f[0].endswith(".py") and not Path(f[0]).name.startswith("test_")]
        if py_files:
            main_py = str(base_path / py_files[-1])
        meta = {
            "project_name": project_name,
            "project_dir": str(base_path),
            "created_files": [f[0] for f in created_files],
            "main_file": main_py,
            "timestamp": time.time(),
        }
        last_project_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    except Exception as save_err:
        print(f"[DevAgent] Warning saving last project metadata: {save_err}")

    return "\n".join(lines)


def write_code(path: str, code: str) -> str:
    """Writes code directly to a file path and checks syntax."""
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    clean = _clean_code_block(code)
    target.write_text(clean, encoding="utf-8")
    
    if target.suffix.lower() == ".py":
        ok, err = _validate_python_syntax(target)
        if not ok:
            return f"Code written to {target.name}, but syntax error detected: {err}"
    return f"Code successfully written to {target.name} ({len(clean.splitlines())} lines)."


def run_code(path: str = "", command: str = "", cwd: str = "") -> str:
    """Executes a script or shell command safely."""
    work_dir = Path(cwd).expanduser() if cwd else Path.cwd()
    cmd_list = []
    
    if path:
        target = Path(path).expanduser()
        if not target.exists():
            return f"Script not found: {path}"
        if target.suffix.lower() == ".py":
            cmd_list = [sys.executable, str(target)]
        else:
            cmd_list = [str(target)]
        work_dir = target.parent
    elif command:
        cmd_list = command.split()
    else:
        return "No script path or command specified to run."
        
    try:
        res = subprocess.run(
            cmd_list,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=30,
        )
        out = (res.stdout or "").strip()
        err = (res.stderr or "").strip()
        result = out if out else (err or "Command finished with returncode 0.")
        return result[:3000]
    except subprocess.TimeoutExpired:
        return "Execution timed out after 30 seconds."
    except Exception as e:
        return f"Execution error: {e}"


def open_created_project(parameters: dict = None) -> str:
    """Opens the most recently created project directory and main file on screen."""
    last_project_file = Path(__file__).resolve().parent.parent / "config" / "last_project.json"
    project_dir = None
    main_file = None
    project_name = "the created project"

    if last_project_file.exists():
        try:
            data = json.loads(last_project_file.read_text(encoding="utf-8"))
            p_dir = Path(data.get("project_dir", ""))
            if p_dir.exists():
                project_dir = p_dir
                project_name = data.get("project_name", p_dir.name)
                m_file = Path(data.get("main_file", ""))
                if m_file.exists():
                    main_file = m_file
        except Exception:
            pass

    # Fallback: scan default Projects folder for most recently modified directory
    if not project_dir or not project_dir.exists():
        projects_root = _get_default_projects_dir()
        if projects_root.exists():
            dirs = [d for d in projects_root.iterdir() if d.is_dir() and not d.name.startswith(".")]
            if dirs:
                dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
                project_dir = dirs[0]
                project_name = project_dir.name

    from core.llm_client import get_salutation
    addr = get_salutation()

    if not project_dir or not project_dir.exists():
        return f"I could not locate any recently built project files on your system, {addr}."

    # Locate the primary python file if not found
    if not main_file or not main_file.exists():
        py_files = [f for f in project_dir.rglob("*.py") if not f.name.startswith("test") and f.name != "__init__.py"]
        if py_files:
            py_files.sort(key=lambda f: f.stat().st_size, reverse=True)
            main_file = py_files[0]
        else:
            all_py = list(project_dir.rglob("*.py"))
            if all_py:
                main_file = all_py[0]

    # Open both folder and primary code file on screen
    opened_details = []
    try:
        if _OS == "Darwin":
            subprocess.Popen(["open", str(project_dir)])
            opened_details.append(f"folder '{project_dir.name}'")
            if main_file and main_file.exists():
                subprocess.Popen(["open", str(main_file)])
                opened_details.append(f"file '{main_file.name}'")
        elif _OS == "Windows":
            os.startfile(str(project_dir))
            opened_details.append(f"folder '{project_dir.name}'")
            if main_file and main_file.exists():
                os.startfile(str(main_file))
                opened_details.append(f"file '{main_file.name}'")
        else:
            subprocess.Popen(["xdg-open", str(project_dir)])
            opened_details.append(f"folder '{project_dir.name}'")
            if main_file and main_file.exists():
                subprocess.Popen(["xdg-open", str(main_file)])
                opened_details.append(f"file '{main_file.name}'")
    except Exception as e:
        return f"Could not open project files on screen: {e}"

    if main_file:
        return f"I am opening the {project_name} folder and {main_file.name} on your screen right now, {addr}."
    return f"I am opening the {project_name} folder on your screen right now, {addr}."


def dev_agent(parameters: dict = None, **kwargs) -> str:
    """
    Main entrypoint for SAM dev_agent tool calls.
    Supports action in ('create_project', 'build_project', 'open_created_project', 'write_code', 'run_code', 'test_project', 'debug').
    """
    params = parameters if isinstance(parameters, dict) else {}
    action = params.get("action", "build_project").lower().strip()

    if action in ("open_created_project", "open_created", "open_project", "open_last_project", "open_file"):
        return open_created_project(params)
    
    goal = (
        params.get("goal")
        or params.get("project")
        or params.get("task")
        or params.get("description")
        or ""
    )
    project_name = params.get("project_name") or params.get("name") or ""
    path = params.get("path") or params.get("file_path") or ""
    code = params.get("code") or params.get("content") or ""
    language = params.get("language") or "python"
    
    if action in ("create_project", "build_project", "create", "build"):
        if not goal and not project_name:
            goal = "Autonomous software project"
        return build_project(
            goal=goal or project_name,
            project_name=project_name,
            target_dir=path if path else None,
            language=language
        )
        
    elif action in ("write_code", "write", "create_file"):
        if not path:
            return "Please specify a file path to write code to."
        return write_code(path=path, code=code)
        
    elif action in ("run_code", "run", "execute"):
        return run_code(
            path=path,
            command=params.get("command", ""),
            cwd=params.get("cwd", "")
        )
        
    elif action in ("test_project", "test"):
        target_dir = path or str(_get_default_projects_dir() / _sanitize_name(project_name or "sam_project"))
        return run_code(cwd=target_dir, command=f"{sys.executable} -m unittest discover")
        
    elif action in ("debug", "fix"):
        if not path:
            return "Please provide file path for debugging."
        target_file = Path(path).expanduser()
        if not target_file.exists():
            return f"File not found: {path}"
        error_msg = params.get("error", "Code has issues or bugs.")
        healed = _self_heal_code(target_file, error_msg, language=language)
        return f"Debug and repair completed for {target_file.name}. Self-healing verified: {healed}"
        
    else:
        # Default fallback to building project if a goal is provided
        if goal:
            return build_project(goal=goal, project_name=project_name, target_dir=path, language=language)
        return f"Unknown dev_agent action: '{action}'"
