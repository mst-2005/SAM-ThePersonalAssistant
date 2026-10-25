"""
code_helper.py — SAM Code Intelligence Helper
Provides fast code review, refactoring, debugging, explanation, and test generation.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from core.brain_router import call_brain


def _clean_code_block(raw: str) -> str:
    raw = raw.strip()
    m = re.search(r"```(?:\w+)?\n(.*?)```", raw, re.DOTALL)
    if m:
        return m.group(1).strip()
    raw = re.sub(r"^```[a-zA-Z0-9_]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return raw.strip()


def code_helper(parameters: dict = None, **kwargs) -> str:
    params = parameters if isinstance(parameters, dict) else {}
    action = params.get("action", "explain").lower().strip()
    path = params.get("path") or params.get("file_path") or ""
    code = params.get("code") or params.get("content") or ""
    instruction = params.get("instruction") or params.get("goal") or params.get("query") or ""
    
    # Read file content if path provided
    file_path = None
    if path:
        file_path = Path(path).expanduser()
        if file_path.exists() and file_path.is_file():
            try:
                code = file_path.read_text(encoding="utf-8", errors="replace")[:15000]
            except Exception as e:
                return f"Could not read file {path}: {e}"

    if not code and not instruction:
        return "No code or instruction provided to code_helper."

    if action in ("review", "audit"):
        prompt = (
            f"Review this code for bugs, security vulnerabilities, performance bottlenecks, and style:\n\n"
            f"```\n{code}\n```\n\n"
            "Provide a concise, numbered summary of critical issues and actionable recommendations."
        )
        res = call_brain(prompt, system="You are an expert code reviewer. Be concise, direct, and constructive.", task_type="complex")
        return res.get("content", "").strip()

    elif action in ("explain", "understand"):
        prompt = (
            f"Explain how this code works clearly in plain English:\n\n"
            f"```\n{code}\n```\n\n"
            f"Specific focus: {instruction or 'Overall architecture and logic flow'}"
        )
        res = call_brain(prompt, system="You are a senior software educator. Explain code clearly and concisely.", task_type="auto")
        return res.get("content", "").strip()

    elif action in ("fix", "debug", "refactor"):
        prompt = (
            f"Refactor and fix this code:\n\n"
            f"```\n{code}\n```\n\n"
            f"Requirements / Problem to solve: {instruction or 'Fix bugs, improve readability and performance.'}\n\n"
            "Return ONLY the complete, improved code inside ``` code fences."
        )
        res = call_brain(prompt, system="You are an elite software engineer. Return full, clean, working code.", task_type="complex")
        improved = _clean_code_block(res.get("content", ""))
        
        # If file_path was given, write back to file
        if file_path and file_path.exists() and improved:
            file_path.write_text(improved, encoding="utf-8")
            return f"Code in {file_path.name} refactored and saved successfully ({len(improved.splitlines())} lines)."
        return improved

    elif action in ("test", "generate_tests"):
        prompt = (
            f"Generate comprehensive unit tests for this code using standard pytest or unittest:\n\n"
            f"```\n{code}\n```\n\n"
            "Return ONLY the runnable test code inside ``` code fences."
        )
        res = call_brain(prompt, system="You are an automated testing expert. Write comprehensive, robust unit tests.", task_type="complex")
        test_code = _clean_code_block(res.get("content", ""))
        
        if file_path and file_path.exists():
            test_file = file_path.parent / f"test_{file_path.name}"
            test_file.write_text(test_code, encoding="utf-8")
            return f"Unit tests generated and saved to {test_file.name} ({len(test_code.splitlines())} lines)."
        return test_code

    else:
        prompt = f"Code:\n```\n{code}\n```\n\nRequest: {instruction or action}"
        res = call_brain(prompt, system="You are a helpful software engineering assistant.", task_type="auto")
        return res.get("content", "").strip()
