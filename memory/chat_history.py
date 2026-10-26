"""
chat_history.py — Persistent Conversation History Manager for SAM.

Records all user and SAM conversation exchanges to disk (memory/chat_history.json),
enabling cross-session persistence, searching, and viewing via the HUD interface
and voice/intent commands.
"""
from __future__ import annotations

import json
import re
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
HISTORY_FILE = BASE_DIR / "memory" / "chat_history.json"
_lock = threading.Lock()
MAX_HISTORY_ENTRIES = 5000


def _ensure_file():
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not HISTORY_FILE.exists():
        with _lock:
            try:
                HISTORY_FILE.write_text("[]", encoding="utf-8")
            except Exception:
                pass


def save_message(role: str, content: str) -> dict:
    """
    Appends a new message turn to chat_history.json.
    Role is typically 'User' or 'SAM'.
    """
    clean_role = "User" if role.lower().startswith("you") or role.lower() == "user" else "SAM"
    text = str(content or "").strip()
    if not text:
        return {}

    # Strip tool calls from saved text so records are clean dialogue
    if "<|tool_call>" in text:
        text = re.sub(r"<\|tool_call>.*?<tool_call\|>", "", text, flags=re.DOTALL).strip()
    if not text:
        text = "Action executed successfully."

    entry = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "role": clean_role,
        "content": text,
    }

    _ensure_file()
    with _lock:
        try:
            if HISTORY_FILE.exists():
                raw = HISTORY_FILE.read_text(encoding="utf-8")
                history = json.loads(raw) if raw.strip() else []
            else:
                history = []

            if not isinstance(history, list):
                history = []

            history.append(entry)
            if len(history) > MAX_HISTORY_ENTRIES:
                history = history[-MAX_HISTORY_ENTRIES:]

            HISTORY_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            print(f"[ChatHistory] Failed to save message: {exc}")

    return entry


def load_messages(search: str = "", limit: int = 500) -> List[Dict]:
    """
    Loads saved chat history, latest first or filtered by search keyword.
    """
    _ensure_file()
    with _lock:
        try:
            if not HISTORY_FILE.exists():
                return []
            raw = HISTORY_FILE.read_text(encoding="utf-8")
            history = json.loads(raw) if raw.strip() else []
            if not isinstance(history, list):
                return []
        except Exception as exc:
            print(f"[ChatHistory] Failed to read history: {exc}")
            return []

    if search and search.strip():
        kw = search.strip().lower()
        history = [m for m in history if kw in m.get("content", "").lower() or kw in m.get("role", "").lower()]

    if limit and limit > 0:
        return history[-limit:]
    return history


def clear_history() -> bool:
    """Clears all persisted chat messages."""
    _ensure_file()
    with _lock:
        try:
            HISTORY_FILE.write_text("[]", encoding="utf-8")
            return True
        except Exception as exc:
            print(f"[ChatHistory] Failed to clear history: {exc}")
            return False


def get_recent_summary(max_turns: int = 4) -> str:
    """
    Returns a human-readable text summary of the most recent turns.
    Useful for voice queries like 'what did we talk about earlier?'.
    """
    messages = load_messages(limit=max_turns * 2)
    if not messages:
        return "No previous conversations found in local memory."

    lines = []
    for msg in messages:
        role = msg.get("role", "Unknown")
        ts = msg.get("timestamp", "")
        txt = msg.get("content", "")
        # Shorten text preview
        if len(txt) > 200:
            txt = txt[:197] + "…"
        lines.append(f"[{ts}] {role}: {txt}")

    return "\n".join(lines)
