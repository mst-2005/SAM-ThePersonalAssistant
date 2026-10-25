"""Release validator for SAM.

Run with: python validate.py
This intentionally uses only the Python standard library so it can validate a
fresh checkout before optional runtime dependencies are installed.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQUIRED = [
    "main.py", "ui.py", "requirements.txt", "setup.py", "readme.md",
    "core/brain_router.py", "core/autonomous_agent.py", "memory/memory_manager.py",
    "actions/file_controller.py", "actions/browser_control.py",
    "dashboard/server.py", "dashboard/static/app.html", "dashboard/static/login.html",
]
SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]


def main() -> int:
    errors: list[str] = []
    for rel in REQUIRED:
        if not (ROOT / rel).exists():
            errors.append(f"missing required file: {rel}")

    for path in ROOT.rglob("*.py"):
        if any(part in {"__pycache__", ".git", "tests", ".venv", "venv"} for part in path.parts):
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except Exception as exc:
            errors.append(f"syntax error: {path}: {exc}")

    cfg = ROOT / "config" / "api_keys.json"
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                errors.append("config/api_keys.json must contain a JSON object")
        except Exception as exc:
            errors.append(f"invalid config/api_keys.json: {exc}")

    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in {"__pycache__", ".git", ".venv", "venv"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if path.name in {"api_keys.example.json", "sam.key", "sam.crt"} or "certs" in path.parts:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f"possible secret material found in: {path.relative_to(ROOT)}")
                break

    if errors:
        print("SAM release validation FAILED")
        for error in errors:
            print(" -", error)
        return 1
    print(f"SAM release validation OK — Python {sys.version.split()[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
