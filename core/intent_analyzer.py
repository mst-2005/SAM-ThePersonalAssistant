"""
intent_analyzer.py — Ultra-Fast Rule-Based NLP & Tool Intent Router
Intercepts common SAM requests (overnight projects, PC file operations,
volume, screen vision, system status) and generates instant tool calls in <1ms,
bypassing cloud LLM roundtrip latency.
"""
from __future__ import annotations

import datetime
import re
from typing import Optional


def analyze_query_fast(query: str) -> Optional[str]:
    q_raw = query.strip()
    q_low = q_raw.lower()
    
    # ── 1. Overnight & Autonomous Projects ──────────────────────────────
    overnight_match = re.search(
        r"(?:build|create|start|make|run)\s+(?:me\s+)?(?:an?\s+)?overnight\s+project\s*[:\s]*(.*)",
        q_low,
    )
    if overnight_match:
        goal = overnight_match.group(1).strip() or "Autonomous software project"
        return f'<|tool_call>call:autonomous_task{{"project": "{goal}"}}<tool_call|>'
        
    project_match = re.search(
        r"(?:build|create|generate|make)\s+(?:me\s+)?(?:an?\s+)?(.*?project.*)",
        q_low,
    )
    if project_match:
        goal = project_match.group(1).strip()
        if goal:
            # Clean outer quotes if any
            goal = goal.strip('“"\'”')
            return f'<|tool_call>call:dev_agent{{"action": "build_project", "goal": "{goal}"}}<tool_call|>'

    # ── 2. Project / Task Monitoring ────────────────────────────────────
    if any(q_low == phrase or q_low.startswith(phrase) for phrase in [
        "background monitor", "project status", "task status",
        "overnight status", "how is my project", "how is the project",
        "what got finished overnight", "check background project",
        "overnight project status", "check project status"
    ]):
        return '<|tool_call>call:background_monitor{}<tool_call|>'

    # ── 3. PC Data & File Control ───────────────────────────────────────
    if q_low in [
        "organize desktop", "organize my desktop", "clean desktop",
        "clean my desktop", "tidy desktop", "tidy my desktop"
    ]:
        return '<|tool_call>call:file_controller{{"action": "organize_desktop"}}<tool_call|>'

    if q_low in ["list desktop", "list files on desktop", "show desktop files", "what's on my desktop", "what is on my desktop"]:
        return '<|tool_call>call:file_controller{{"action": "list", "path": "desktop"}}<tool_call|>'

    if q_low in ["list downloads", "show downloads", "what is in downloads", "what's in downloads"]:
        return '<|tool_call>call:file_controller{{"action": "list", "path": "downloads"}}<tool_call|>'

    if q_low in ["list projects", "show projects", "what projects do i have"]:
        return '<|tool_call>call:file_controller{{"action": "list", "path": "projects"}}<tool_call|>'

    if q_low in ["disk usage", "disk space", "storage", "storage space", "how much storage", "free disk space", "check disk"]:
        return '<|tool_call>call:file_controller{{"action": "disk_usage"}}<tool_call|>'

    find_match = re.search(r"find\s+file\s+([a-zA-Z0-9_\-\.\*]+)", q_low)
    if find_match:
        fname = find_match.group(1).strip()
        return f'<|tool_call>call:file_controller{{"action": "find", "name": "{fname}"}}<tool_call|>'

    # ── 4. App Launching ────────────────────────────────────────────────
    if q_low.startswith("open ") or q_low.startswith("launch "):
        target_name = q_raw.split(" ", 1)[1].strip()
        # If opening a folder
        if target_name.lower() in ("desktop", "downloads", "documents", "pictures", "projects", "music", "videos"):
            return f'<|tool_call>call:file_controller{{"action": "open", "path": "{target_name.lower()}"}}<tool_call|>'
        return f'<|tool_call>call:open_app{{"app_name": "{target_name}"}}<tool_call|>'

    # ── 5. System Audio & Settings ──────────────────────────────────────
    if q_low in ["mute", "mute sound", "mute volume", "silence"]:
        return '<|tool_call>call:computer_settings{{"action": "mute"}}<tool_call|>'
    if q_low in ["unmute", "unmute sound", "restore sound"]:
        return '<|tool_call>call:computer_settings{{"action": "unmute"}}<tool_call|>'
    if q_low in ["volume up", "increase volume", "louder"]:
        return '<|tool_call>call:computer_settings{{"action": "volume_up"}}<tool_call|>'
    if q_low in ["volume down", "decrease volume", "lower volume", "quieter"]:
        return '<|tool_call>call:computer_settings{{"action": "volume_down"}}<tool_call|>'

    # ── 6. Vision / Screen / Camera ─────────────────────────────────────
    if any(phrase in q_low for phrase in [
        "what is on my screen", "what's on my screen", "read my screen",
        "look at my screen", "analyze my screen", "what do you see on screen"
    ]):
        return '<|tool_call>call:screen_processor{{"mode": "screen"}}<tool_call|>'

    if any(phrase in q_low for phrase in [
        "look at me", "what do you see on camera", "look at camera",
        "check webcam", "check camera", "look at webcam"
    ]):
        return '<|tool_call>call:screen_processor{{"mode": "camera"}}<tool_call|>'

    # ── 7. Weather ──────────────────────────────────────────────────────
    if "weather" in q_low and len(q_low.split()) <= 6:
        return f'<|tool_call>call:web_search{{"query": "{query}", "mode": "search"}}<tool_call|>'

    # ── 8. Time / Date ──────────────────────────────────────────────────
    if q_low in ["what time is it", "what is the time", "current time", "time"]:
        now = datetime.datetime.now().strftime("%I:%M %p")
        return f"The current time is {now}, sir."
        
    if q_low in ["what is the date", "what's the date", "date today", "what day is it"]:
        date = datetime.datetime.now().strftime("%A, %B %d, %Y")
        return f"Today is {date}, sir."

    # ── 9. Simple Math Calculator ───────────────────────────────────────
    math_expr = q_low.replace("raised to", "**").replace("power", "**")
    math_expr = math_expr.replace("plus", "+").replace("minus", "-")
    math_expr = math_expr.replace("times", "*").replace("divided by", "/")
    math_expr = math_expr.replace("what is", "").replace("what's", "").replace("^", "**").strip()
    
    allowed = set("0123456789+-*/.** ()")
    if math_expr and all(c in allowed for c in math_expr) and any(c in "0123456789" for c in math_expr) and any(c in "+-*/" for c in math_expr):
        try:
            res = eval(math_expr)
            return f"That calculates to {res}, sir."
        except Exception:
            pass

    # ── 10. Hardware System Status ──────────────────────────────────────
    if q_low in ["status", "system status", "how is the system", "system load", "stats", "hardware status"]:
        return '<|tool_call>call:system_status{}<tool_call|>'

    # ── 10b. Time & Calendar ───────────────────────────────────────────
    if any(q_low == phrase or q_low.startswith(phrase) for phrase in [
        "what time is it", "what is the time", "tell me the time", "current time", "what's the time", "time now"
    ]):
        return '<|tool_call>call:reminder{{"action": "time"}}<tool_call|>'

    if any(q_low == phrase or q_low.startswith(phrase) for phrase in [
        "check calendar", "check my calendar", "what's on my calendar", "what is on my calendar",
        "show calendar", "open calendar", "what is today's date", "what is the date",
        "today's date", "what day is it", "calendar today", "my schedule today"
    ]):
        return '<|tool_call>call:reminder{{"action": "calendar"}}<tool_call|>'

    # ── 11. Reminders & Scheduling ──────────────────────────────────────
    remind_min_match = re.search(r"remind\s+(?:me\s+)?in\s+(\d+(?:\.\d+)?)\s*(?:m|min|minute|minutes)\s+(?:to\s+)?(.*)", q_low)
    if remind_min_match:
        mins = remind_min_match.group(1).strip()
        task = remind_min_match.group(2).strip() or "Reminder"
        return f'<|tool_call>call:reminder{{"action": "set", "minutes": {mins}, "message": "{task}"}}<tool_call|>'

    remind_sec_match = re.search(r"remind\s+(?:me\s+)?in\s+(\d+)\s*(?:s|sec|second|seconds)\s+(?:to\s+)?(.*)", q_low)
    if remind_sec_match:
        secs = remind_sec_match.group(1).strip()
        task = remind_sec_match.group(2).strip() or "Reminder"
        return f'<|tool_call>call:reminder{{"action": "set", "seconds": {secs}, "message": "{task}"}}<tool_call|>'

    if q_low.startswith("set a reminder to ") or q_low.startswith("set reminder to "):
        task = re.sub(r"^set (?:a )?reminder to ", "", q_low).strip()
        return f'<|tool_call>call:reminder{{"action": "set", "message": "{task}", "minutes": 10}}<tool_call|>'

    if q_low in ["list reminders", "show reminders", "my reminders", "check reminders", "what are my reminders"]:
        return '<|tool_call>call:reminder{{"action": "list"}}<tool_call|>'

    if q_low in ["cancel reminders", "clear reminders", "delete all reminders"]:
        return '<|tool_call>call:reminder{{"action": "cancel"}}<tool_call|>'

    # ── 12. Cell Phone Connection & Phone Calling ───────────────────────
    if any(q_low == phrase or q_low.startswith(phrase) for phrase in [
        "connect my phone", "connect my cell phone", "can i connect my phone",
        "how to connect my phone", "pair my phone", "phone status", "mobile status"
    ]):
        return '<|tool_call>call:phone_notifier{{"action": "status"}}<tool_call|>'

    save_phone_match = re.search(r"(?:save|set|my)\s+(?:cell\s+)?phone\s*(?:number)?\s*(?:is)?\s*([+0-9\-\s]{7,20})", q_low)
    if save_phone_match:
        pnum = save_phone_match.group(1).strip()
        return f'<|tool_call>call:phone_notifier{{"action": "configure", "phone_number": "{pnum}"}}<tool_call|>'

    if q_low in ["call my phone", "call me", "call my cell", "dial my phone"]:
        return '<|tool_call>call:phone_notifier{{"action": "call", "message": "Good day sir, this is SAM calling with your status report."}}<tool_call|>'

    # ── 13. Emotional Support & Human Resonance (SAM Care) ────────────
    # 13a. Joy, Excitement & Celebrating Wins
    if any(phrase in q_low for phrase in [
        "i am so happy", "i'm happy", "i'm so happy", "feeling happy", "feel happy",
        "i got the job", "i passed my exam", "i passed", "we won", "i won",
        "great news", "wonderful news", "amazing news", "i did it", "we did it",
        "celebrate", "celebrating", "i feel great", "feeling great", "i feel amazing",
        "i'm excited", "so excited", "best day ever"
    ]):
        return (
            "That is incredible news, sir! I am genuinely thrilled and celebrating with you! "
            "You worked so hard for this, and seeing your efforts pay off is truly well-deserved. "
            "Take a moment to soak in this victory! Would you like me to play some celebratory music to mark the moment?"
        )

    # 13b. Breathing & Calming Exercises
    if any(phrase in q_low for phrase in [
        "calm me down", "help me relax", "breathing exercise", "help me breathe",
        "i need to calm down", "panic attack", "guided breathing", "box breathing", "help me relax"
    ]):
        return '<|tool_call>call:emotional_support{{"action": "breathe"}}<tool_call|>'

    # 13c. Cheer me up / Tell me a joke / Light up mood
    if any(phrase in q_low for phrase in [
        "cheer me up", "make me smile", "tell me something funny", "light up my mood",
        "lift my spirits", "make me laugh", "tell me a joke"
    ]):
        return '<|tool_call>call:emotional_support{{"action": "cheer"}}<tool_call|>'

    # 13d. Relaxing / Ambient Music
    if any(phrase in q_low for phrase in [
        "play relaxing music", "play calming music", "play relax music",
        "play soothing music", "calm music", "relaxing sounds", "play lofi"
    ]):
        return '<|tool_call>call:emotional_support{{"action": "music", "mood": "relax"}}<tool_call|>'

    # 13e. Mood History & Emotional Tracking
    if any(phrase in q_low for phrase in [
        "how is my mood", "my mood trends", "emotional wellness", "mood history", "how have i been feeling"
    ]):
        return '<|tool_call>call:emotional_support{{"action": "trends"}}<tool_call|>'

    # 13f. Anger & Frustration
    if any(phrase in q_low for phrase in [
        "i am so angry", "i'm angry", "i am furious", "so pissed", "this is so frustrating",
        "i hate this", "i am frustrated", "i'm frustrated", "i can't take this anymore"
    ]):
        return (
            "I hear you completely, sir. Take a moment to vent—I am listening without judgment. "
            "It is entirely valid to feel furious when things don't go right. "
            "Take a slow breath. When you're ready, tell me what happened, or let me handle the computer chores while you step away."
        )

    # 13g. Anxiety & Overwhelm
    if any(phrase in q_low for phrase in [
        "i am anxious", "i'm anxious", "feeling anxious", "so anxious", "having anxiety",
        "i'm overwhelmed", "i feel overwhelmed", "so much stress", "too much pressure",
        "i can't handle this", "i'm nervous", "feeling nervous"
    ]):
        return (
            "Take a deep breath with me, sir. You do not have to conquer everything all at once. "
            "Let's break things down together, one single step at a time. "
            "Would you like to do a quick 30-second guided breathing exercise, or shall I dim the screen so you can pause for a minute?"
        )

    # 13h. Sadness, Grief & Rough Days
    if any(phrase in q_low for phrase in [
        "i am sad", "i'm sad", "feeling sad", "feel sad",
        "i am depressed", "i'm depressed", "feeling depressed",
        "feeling down", "i feel down", "i'm feeling low", "feeling low",
        "i feel lonely", "i am lonely", "feeling lonely",
        "i had a bad day", "i had a terrible day", "rough day today", "terrible day",
        "i am stressed", "i'm stressed", "feeling stressed", "stressed out"
    ]):
        return (
            "I am right here with you, sir. I am truly sorry you are having a difficult time. "
            "Please know that you are deeply valued, and your well-being matters far more than any deadline or task. "
            "How are you feeling physically right now? Have you stayed hydrated and had something to eat today? "
            "If you need a moment, I can dim your display, play soothing music, guide a calming breath, or tell you something cheerful to light up your mood."
        )

    # 13i. Physical Fatigue & Illness
    if any(phrase in q_low for phrase in [
        "i have a headache", "my head hurts", "i don't feel good", "not feeling well",
        "i am sick", "i feel sick", "i'm exhausted", "i am so tired", "i'm tired"
    ]):
        return (
            "I'm very concerned to hear that, sir. Please take a break immediately and step away from the screen. "
            "Drink a glass of water, rest your eyes, and don't push yourself. "
            "Would you like me to set a reminder for you to rest or take medication, or lower the system volume and brightness?"
        )

    return None
