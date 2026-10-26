"""
reminder.py — SAM Scheduled Reminders & Health Alerts
Schedules system notifications, voice reminders, and health check-ins.
Persists reminders to memory/reminders.json so they survive restarts.
"""
from __future__ import annotations

import datetime
import json
import os
import platform
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
REMINDERS_FILE = BASE_DIR / "memory" / "reminders.json"
REMINDERS_FILE.parent.mkdir(parents=True, exist_ok=True)

_ACTIVE_TIMERS: dict[str, threading.Timer] = {}
_OS = platform.system()


def _load_reminders() -> list[dict]:
    if not REMINDERS_FILE.exists():
        return []
    try:
        return json.loads(REMINDERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_reminders(reminders: list[dict]) -> None:
    try:
        REMINDERS_FILE.write_text(json.dumps(reminders, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"[Reminder] Save error: {e}")


def _notify_desktop(title: str, message: str) -> None:
    """Delivers native OS toast notification without external dependencies."""
    if _OS == "Windows":
        try:
            # Use PowerShell to show native Windows toast notification
            ps_script = (
                f"[void] [System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms');"
                f"$notify = New-Object System.Windows.Forms.NotifyIcon;"
                f"$notify.Icon = [System.Drawing.SystemIcons]::Information;"
                f"$notify.Visible = $true;"
                f"$notify.ShowBalloonTip(5000, '{title}', '{message}', [System.Windows.Forms.ToolTipIcon]::Info);"
            )
            subprocess.Popen(["powershell", "-NoProfile", "-Command", ps_script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    elif _OS == "Darwin":
        try:
            subprocess.run(["osascript", "-e", f'display notification "{message}" with title "{title}"'], check=False)
        except Exception:
            pass
    else:
        try:
            subprocess.run(["notify-send", title, message], check=False)
        except Exception:
            pass


def _trigger_reminder(reminder_id: str) -> None:
    reminders = _load_reminders()
    target = None
    remaining = []
    
    for r in reminders:
        if r.get("id") == reminder_id:
            target = r
        else:
            remaining.append(r)
            
    _save_reminders(remaining)
    _ACTIVE_TIMERS.pop(reminder_id, None)
    
    if not target:
        return
        
    title = target.get("title", "SAM Reminder")
    from core.llm_client import get_salutation
    addr = get_salutation()
    message = target.get("message", f"Time is up, {addr}.")
    
    print(f"\n🔔 [REMINDER TRIGGERED]: {title} — {message}")
    _notify_desktop(title, message)
    
    # Optional voice reminder if main TTS is accessible
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        pass


def _parse_delay_seconds(raw_time: str, minutes: float = 0, seconds: float = 0, hours: float = 0) -> float:
    total = seconds + (minutes * 60) + (hours * 3600)
    if total > 0:
        return total
        
    raw = (raw_time or "").lower().strip()
    if not raw:
        return 300.0  # default 5 minutes
        
    # Match patterns like "10 minutes", "10m", "2 hours", "45 seconds"
    m_min = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|min|minute|minutes)", raw)
    if m_min:
        total += float(m_min.group(1)) * 60
        
    m_sec = re.search(r"(\d+(?:\.\d+)?)\s*(?:s|sec|second|seconds)", raw)
    if m_sec:
        total += float(m_sec.group(1))
        
    m_hr = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hour|hours)", raw)
    if m_hr:
        total += float(m_hr.group(1)) * 3600
        
    if total > 0:
        return total
        
    # Try parsing specific clock time like "5:30 pm" or "14:00"
    try:
        now = datetime.datetime.now()
        for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M"):
            try:
                t = datetime.datetime.strptime(raw, fmt).time()
                target_dt = datetime.datetime.combine(now.date(), t)
                if target_dt <= now:
                    target_dt += datetime.timedelta(days=1)
                return (target_dt - now).total_seconds()
            except ValueError:
                continue
    except Exception:
        pass
        
    return 300.0


def set_reminder(
    message: str,
    time_str: str = "",
    minutes: float = 0,
    seconds: float = 0,
    hours: float = 0,
    title: str = "SAM Reminder"
) -> str:
    delay = _parse_delay_seconds(time_str, minutes=minutes, seconds=seconds, hours=hours)
    reminder_id = uuid.uuid4().hex[:8]
    fire_dt = datetime.datetime.now() + datetime.timedelta(seconds=delay)
    fire_str = fire_dt.strftime("%I:%M %p")
    
    reminder_entry = {
        "id": reminder_id,
        "title": title,
        "message": message,
        "target_time": fire_dt.isoformat(),
        "created_at": datetime.datetime.now().isoformat(),
    }
    
    reminders = _load_reminders()
    reminders.append(reminder_entry)
    _save_reminders(reminders)
    
    timer = threading.Timer(delay, _trigger_reminder, args=[reminder_id])
    timer.daemon = True
    timer.start()
    _ACTIVE_TIMERS[reminder_id] = timer
    
    delay_min = int(delay // 60)
    delay_sec = int(delay % 60)
    delay_desc = f"{delay_min} minute(s)" if delay_min > 0 else f"{delay_sec} seconds"
    
    from core.llm_client import get_salutation
    addr = get_salutation()
    return f"Reminder scheduled for {fire_str} ({delay_desc} from now), {addr}: '{message}'."


def list_reminders() -> str:
    from core.llm_client import get_salutation
    addr = get_salutation()
    reminders = _load_reminders()
    if not reminders:
        return f"You have no active reminders scheduled, {addr}."
        
    now = datetime.datetime.now()
    lines = [f"You have {len(reminders)} active reminder(s), {addr}:\n"]
    for r in reminders:
        try:
            target_dt = datetime.datetime.fromisoformat(r["target_time"])
            diff = (target_dt - now).total_seconds()
            if diff <= 0:
                time_desc = "Due now"
            else:
                mins = int(diff // 60)
                time_desc = f"in {mins} min ({target_dt.strftime('%I:%M %p')})"
            lines.append(f"  - ID: {r['id']} | {r['message']} ({time_desc})")
        except Exception:
            lines.append(f"  - ID: {r['id']} | {r['message']}")
            
    return "\n".join(lines)


def cancel_reminder(reminder_id: str = "") -> str:
    from core.llm_client import get_salutation
    addr = get_salutation()
    reminders = _load_reminders()
    if not reminders:
        return f"No reminders to cancel, {addr}."
        
    if not reminder_id:
        # Cancel all
        for t in _ACTIVE_TIMERS.values():
            t.cancel()
        _ACTIVE_TIMERS.clear()
        _save_reminders([])
        return f"All scheduled reminders have been cancelled, {addr}."
        
    remaining = []
    found = False
    for r in reminders:
        if r.get("id") == reminder_id or reminder_id.lower() in r.get("message", "").lower():
            found = True
            timer = _ACTIVE_TIMERS.pop(r.get("id"), None)
            if timer:
                timer.cancel()
        else:
            remaining.append(r)
            
    _save_reminders(remaining)
    if found:
        return f"Reminder {reminder_id} cancelled, {addr}."
    return f"Could not find reminder matching '{reminder_id}', {addr}."


def check_time() -> str:
    """Returns the current local time, period of the day, and date formatted for voice response."""
    from core.llm_client import get_salutation
    addr = get_salutation()
    now = datetime.datetime.now()
    time_str = now.strftime("%I:%M %p").lstrip("0")
    date_str = now.strftime("%A, %B %d, %Y")
    return f"The current time is {time_str} on {date_str}, {addr}."


def check_calendar() -> str:
    """Returns calendar overview: current date, day of year, upcoming scheduled items and events."""
    now = datetime.datetime.now()
    date_str = now.strftime("%A, %B %d, %Y")
    day_num = now.timetuple().tm_yday
    week_num = now.isocalendar()[1]
    
    # Load upcoming reminders / scheduled calendar entries
    reminders = _load_reminders()
    upcoming_lines = []
    for r in reminders:
        try:
            target_dt = datetime.datetime.fromisoformat(r["target_time"])
            diff = (target_dt - now).total_seconds()
            if diff > 0:
                mins = int(diff // 60)
                upcoming_lines.append(f"  - {r['message']} (in {mins} min at {target_dt.strftime('%I:%M %p')})")
        except Exception:
            pass
            
    res = [
        f"Today is {date_str} (Week {week_num}, Day {day_num} of the year).",
    ]
    if upcoming_lines:
        res.append("Upcoming schedule items:")
        res.extend(upcoming_lines)
    else:
        res.append("Your schedule is clear for today with no pending events or alerts.")
    return "\n".join(res)


def reminder(parameters: dict = None, **kwargs) -> str:
    params = parameters if isinstance(parameters, dict) else {}
    action = params.get("action", "set").lower().strip()
    message = params.get("message") or params.get("text") or params.get("task") or "Health check-in"
    time_str = params.get("time") or params.get("delay") or ""
    minutes = float(params.get("minutes", 0) or 0)
    seconds = float(params.get("seconds", 0) or 0)
    hours = float(params.get("hours", 0) or 0)
    reminder_id = params.get("id") or params.get("reminder_id") or ""
    
    if action in ("time", "current_time", "what_time", "clock"):
        return check_time()
    elif action in ("calendar", "date", "today", "schedule", "events"):
        return check_calendar()
    elif action in ("set", "create", "add"):
        return set_reminder(message=message, time_str=time_str, minutes=minutes, seconds=seconds, hours=hours)
    elif action in ("list", "show", "get"):
        return list_reminders()
    elif action in ("cancel", "delete", "clear"):
        return cancel_reminder(reminder_id)
    else:
        return set_reminder(message=message, time_str=time_str, minutes=minutes, seconds=seconds, hours=hours)
