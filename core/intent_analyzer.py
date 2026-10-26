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


def analyze_query_fast(query: str, address: Optional[str] = None) -> Optional[str]:
    q_raw = query.strip()
    # Strip optional wake greeting ("Hey Sam, ...", "Sam, ...") so voice and text commands match fast rules
    stripped = re.sub(r"^(?:hey|hi|hello|ok)?\s*\b(?:sam|sem)\b[\s,.:;!?]*", "", q_raw, flags=re.IGNORECASE).strip()
    if stripped:
        q_raw = stripped
    q_low = q_raw.lower()

    if address is None:
        try:
            from core.llm_client import get_salutation
            address = get_salutation()
        except Exception:
            address = "Sir"

    # ── 0. Standby / Sleep Mode ─────────────────────────────────────────
    if any(q_low == phrase or q_low.startswith(phrase) for phrase in [
        "go to sleep", "sleep mode", "stop listening", "standby mode", "enter sleep mode", "pause listening", "sleep now"
    ]):
        return '<|tool_call>call:sleep_mode{}<tool_call|>'

    # ── 0b. Instant Salutation / Addressing Command ─────────────────────
    sal_match = re.search(
        r"^(?:please\s+)?(?:call\s+me|address\s+me\s+as|set\s+(?:my\s+)?(?:salutation|title)\s+to|change\s+(?:my\s+)?(?:salutation|title)\s+to|switch\s+(?:my\s+)?(?:salutation\s+|title\s+)?to|change\s+to)\s+(.*)",
        q_low,
    )
    if not sal_match:
        sal_match = re.search(r"^my\s+name\s+is\s+([a-zA-Z0-9_\- ]+)(?:,?\s+call\s+me\s+(?:by\s+)?(?:my\s+name|[a-zA-Z0-9_\- ]+))?", q_low)
    if sal_match:
        raw_val = sal_match.group(1).strip().strip(" .,!?:;'\"")
        # Exclude "call me on my phone" or "call me"
        if raw_val and not any(raw_val.startswith(p) for p in ("on my phone", "later", "back", "when", "if")):
            if raw_val.lower() in ("ma'am", "maam", "madam", "mam"):
                return '<|tool_call>call:set_salutation{"salutation": "Ma\'am"}<tool_call|>'
            elif raw_val.lower() in ("sir", "mister", "mr"):
                return '<|tool_call>call:set_salutation{"salutation": "Sir"}<tool_call|>'
            elif raw_val.lower() in ("other", "other name"):
                return '<|tool_call>call:set_salutation{"salutation": "Other", "other_name": "friend"}<tool_call|>'
            else:
                proper_name = raw_val.title()
                return f'<|tool_call>call:set_salutation{{"salutation": "Other", "other_name": "{proper_name}"}}<tool_call|>'
    
    # ── 0c. Previous Chats / Conversation History ───────────────────────
    if any(q_low == phrase or q_low.startswith(phrase) or phrase in q_low for phrase in [
        "previous chats", "previous chat", "past chats", "past chat",
        "chat history", "show previous chats", "show chat history",
        "view chat history", "show my chats", "view past conversations",
        "previous conversations", "show previous conversations",
        "what did we talk about earlier", "open chat history", "open previous chats",
        "show past messages", "conversation history"
    ]):
        return '<|tool_call>call:chat_history{"action": "show"}<tool_call|>'

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

    # ── 2b. Open Created Project / File on Screen ─────────────────────────
    if any(phrase in q_low for phrase in [
        "the file what u created open it on my screen",
        "the file u created open it on my screen",
        "the file you created open it on my screen",
        "the file what u created open it",
        "the file u created open it",
        "open the file you created",
        "open the file u created",
        "open the file what you created",
        "open what you created",
        "open what u created",
        "open created project",
        "open created file",
        "open my created project",
        "open last project",
        "open recent project",
        "open the project you made",
        "open the file you made",
        "open the project you created",
    ]) or (
        ("created" in q_low or "built" in q_low or "made" in q_low)
        and ("file" in q_low or "project" in q_low)
        and "open" in q_low
    ):
        return '<|tool_call>call:dev_agent{{"action": "open_created_project"}}<tool_call|>'

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

    # ── 4b. Music & Video Playback (Spotify & YouTube) ───────────────────
    # YouTube through Google Chrome: e.g. "Play it on YouTube through Google Chrome Instead"
    yt_chrome_match = re.search(
        r"play(?:\s+(.+?))?\s+(?:on|in|through)\s+youtube\s+(?:on|in|through)\s+(google chrome|chrome)(?:\s+instead)?",
        q_low,
    )
    if not yt_chrome_match:
        yt_chrome_match = re.search(
            r"play(?:\s+(.+?))?\s+(?:on|in|through)\s+(google chrome|chrome)\s+(?:on|in|through)\s+youtube(?:\s+instead)?",
            q_low,
        )
    if yt_chrome_match:
        song = (yt_chrome_match.group(1) or "it").strip()
        return f'<|tool_call>call:youtube_video{{"action": "play", "query": "{song}", "browser": "chrome"}}<tool_call|>'

    if "youtube" in q_low and ("chrome" in q_low or "google chrome" in q_low) and "play" in q_low:
        clean = re.sub(r"\b(?:play|it|on|in|through|google|chrome|youtube|instead)\b", "", q_low).strip()
        song = clean or "it"
        return f'<|tool_call>call:youtube_video{{"action": "play", "query": "{song}", "browser": "chrome"}}<tool_call|>'

    # General YouTube play: "play <song> on youtube"
    yt_match = re.search(r"play\s+(.+?)\s+on\s+youtube(?:\s+instead)?", q_low)
    if yt_match:
        song = yt_match.group(1).strip()
        return f'<|tool_call>call:youtube_video{{"action": "play", "query": "{song}"}}<tool_call|>'

    # Specific Spotify play: "play <song> on spotify"
    spotify_match = re.search(r"play\s+(.+?)\s+on\s+spotify", q_low)
    if spotify_match:
        song = spotify_match.group(1).strip()
        return f'<|tool_call>call:open_app{{"action": "play_spotify", "song": "{song}"}}<tool_call|>'

    # General song play: "play believer by imagine dragons", "play starboy", etc.
    # Exclude relaxing/calming routines handled in emotional support
    if q_low.startswith("play ") and not any(w in q_low for w in ("relax", "calm", "soothing", "lofi")):
        song = q_low[5:].strip()
        song = re.sub(r"^(?:song|track|music)\s+", "", song).strip()
        if song:
            return f'<|tool_call>call:open_app{{"action": "play_music", "song": "{song}"}}<tool_call|>'

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
    screen_triggers = [
        "what is on my screen", "what's on my screen", "whats on my screen",
        "read my screen", "look at my screen", "analyze my screen", "what do you see on screen",
        "whts ging on my screen", "what's going on my screen", "whats going on my screen",
        "what is going on my screen", "what is happening on my screen", "what's happening on my screen",
        "check my screen", "check screen", "inspect screen", "look at screen", "read screen",
        "see my screen", "look on my screen"
    ]
    if any(phrase in q_low for phrase in screen_triggers) or (
        "screen" in q_low and any(w in q_low for w in ("what", "whts", "look", "read", "see", "check", "going on", "ging on", "analyze", "inspect"))
    ):
        return '<|tool_call>call:screen_processor{{"action": "screen", "text": "Describe what is currently visible on my screen in 2 concise sentences."}}<tool_call|>'

    if any(phrase in q_low for phrase in [
        "look at me", "what do you see on camera", "look at camera",
        "check webcam", "check camera", "look at webcam"
    ]):
        return '<|tool_call>call:screen_processor{{"action": "camera"}}<tool_call|>'

    # ── 7. Weather ──────────────────────────────────────────────────────
    if "weather" in q_low and len(q_low.split()) <= 6:
        return f'<|tool_call>call:web_search{{"query": "{query}", "mode": "search"}}<tool_call|>'

    # ── 8. Time / Date ──────────────────────────────────────────────────
    if q_low in ["what time is it", "what is the time", "current time", "time"]:
        now = datetime.datetime.now().strftime("%I:%M %p")
        return f"The current time is {now}, {address}."
        
    if q_low in ["what is the date", "what's the date", "date today", "what day is it"]:
        date = datetime.datetime.now().strftime("%A, %B %d, %Y")
        return f"Today is {date}, {address}."

    # ── 9. Simple Math Calculator ───────────────────────────────────────
    math_expr = q_low.replace("raised to", "**").replace("power", "**")
    math_expr = math_expr.replace("plus", "+").replace("minus", "-")
    math_expr = math_expr.replace("times", "*").replace("divided by", "/")
    math_expr = math_expr.replace("what is", "").replace("what's", "").replace("^", "**").strip()
    
    allowed = set("0123456789+-*/.** ()")
    if math_expr and all(c in allowed for c in math_expr) and any(c in "0123456789" for c in math_expr) and any(c in "+-*/" for c in math_expr):
        try:
            res = eval(math_expr)
            return f"That calculates to {res}, {address}."
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
        return f'<|tool_call>call:phone_notifier{{"action": "call", "message": "Good day {address}, this is SAM calling with your status report."}}<tool_call|>'

    # ── 13. Emotional Support & Human Resonance (SAM Care) ────────────
    # 13a. Joy, Excitement & Celebrating Wins
    if any(phrase in q_low for phrase in [
        "i am happy", "i'm happy", "i am so happy", "i'm so happy", "feeling happy", "feel happy",
        "i got the job", "i passed my exam", "i passed", "we won", "i won",
        "great news", "wonderful news", "amazing news", "i did it", "we did it",
        "celebrate", "celebrating", "i feel great", "feeling great", "i feel amazing",
        "i'm excited", "so excited", "best day ever"
    ]):
        return (
            f"That is incredible news, {address}! I am genuinely thrilled and celebrating with you! "
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
            f"I hear you completely, {address}. Take a moment to vent—I am listening without judgment. "
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
            f"Take a deep breath with me, {address}. You do not have to conquer everything all at once. "
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
            f"I am right here with you, {address}. I am truly sorry you are having a difficult time. "
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
            f"I'm very concerned to hear that, {address}. Please take a break immediately and step away from the screen. "
            "Drink a glass of water, rest your eyes, and don't push yourself. "
            "Would you like me to set a reminder for you to rest or take medication, or lower the system volume and brightness?"
        )

    return None
