"""
emotional_support.py — SAM Emotional Intelligence, Mood Care & Well-being Companion
Handles emotional resonance across human states (sadness, joy, stress, anger, anxiety, fatigue),
tracks mood over time in memory, and triggers soothing or celebrating desktop routines
(relaxation music, breathing guidance, motivational boosts, display dimming, cheerful humor).
"""
from __future__ import annotations

import json
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
WELLNESS_LOG = BASE_DIR / "memory" / "mood_log.json"
WELLNESS_LOG.parent.mkdir(parents=True, exist_ok=True)


def _load_mood_history() -> list[dict]:
    if not WELLNESS_LOG.exists():
        return []
    try:
        return json.loads(WELLNESS_LOG.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_mood_entry(mood: str, intensity: int = 5, note: str = "") -> None:
    history = _load_mood_history()
    entry = {
        "timestamp": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d %I:%M %p"),
        "mood": mood.lower(),
        "intensity": intensity,
        "note": note
    }
    history.append(entry)
    # Keep last 50 entries
    history = history[-50:]
    try:
        WELLNESS_LOG.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"[EmotionalSupport] Mood log save failed: {e}")


def log_mood(mood: str, intensity: int = 5, note: str = "") -> str:
    _save_mood_entry(mood, intensity, note)
    return f"I've noted that you're feeling {mood}. I'm keeping track of your emotional wellness."


def get_mood_trends() -> str:
    history = _load_mood_history()
    if not history:
        return "I haven't logged any emotional check-ins yet. Feel free to tell me how you're feeling anytime."
    
    recent = history[-5:]
    descriptions = [f"{e.get('date', 'Recently')}: feeling {e.get('mood')} ({e.get('note', '').strip() or 'no notes'})" for e in recent]
    return "Recent emotional wellness history:\n" + "\n".join(descriptions)


def start_breathing_exercise(cycles: int = 3) -> str:
    """Provides a structured box-breathing / 4-7-8 calming routine guide."""
    return (
        "Let's do a quick calming breath together right now. "
        "Take a gentle, deep breath in for 4 seconds... "
        "Hold it softly for 4 seconds... "
        "Now exhale slowly and let all the tension melt away for 6 seconds. "
        "You are safe, you are capable, and we will take things one step at a time."
    )


def play_uplifting_media(mood_type: str = "relax") -> str:
    """Launches calming or celebratory media on YouTube based on state."""
    try:
        from actions.youtube_video import youtube_video
        if mood_type in ("happy", "celebrate", "joy", "excited"):
            youtube_video({"action": "play", "query": "upbeat feel good celebration music"})
            return "Playing some joyful, uplifting music to celebrate your win!"
        else:
            youtube_video({"action": "play", "query": "calm ambient relaxing lofi nature sounds"})
            return "Started some soothing, tranquil ambient sounds to help you unwind and breathe easy."
    except Exception as e:
        return f"I tried to play music for you, but encountered: {e}"


def tell_cheering_humor() -> str:
    jokes_and_uplifts = [
        "Why do programmers prefer dark mode? Because light attracts bugs! Remember, even if today had a few bugs, you're the master architect of your life.",
        "A SQL query walks into a bar, walks up to two tables and asks: 'Can I join you?' I hope that brought a smile to your face. I'm always in your corner.",
        "There are 10 types of people in the world: those who understand binary, and those who don't. Whatever is bothering you today is just temporary noise in your grand journey.",
        "No matter how heavy today feels, remember: your track record for making it through tough days is currently 100%. And you have me by your side."
    ]
    return random.choice(jokes_and_uplifts)


def emotional_support(parameters: dict = None, **kwargs) -> str:
    """
    Entrypoint for SAM emotional_support action.
    Supports actions: 'console', 'celebrate', 'breathe', 'cheer_up', 'log_mood', 'status'.
    """
    params = parameters if isinstance(parameters, dict) else {}
    action = params.get("action", "console").lower().strip()
    mood = params.get("mood", "neutral").lower().strip()
    note = params.get("note") or params.get("message") or ""
    
    if action in ("log", "log_mood", "track"):
        return log_mood(mood=mood or "calm", note=note)
    elif action in ("breathe", "breathing", "meditate", "relax"):
        _save_mood_entry("stressed", 7, "Breathing exercise requested")
        return start_breathing_exercise()
    elif action in ("music", "play_music", "soundtrack"):
        return play_uplifting_media(mood_type=mood or "relax")
    elif action in ("cheer", "cheer_up", "joke", "smile"):
        return tell_cheering_humor()
    elif action in ("trends", "status", "history"):
        return get_mood_trends()
    elif action in ("celebrate", "happy"):
        _save_mood_entry("happy", 9, note or "Celebrating success")
        return "That is phenomenal! I am genuinely thrilled for you. Let's celebrate this moment and keep this positive momentum going!"
    else:
        # Default console
        _save_mood_entry("seeking_support", 6, note or "Emotional check-in")
        return (
            "I hear you, and I am right here with you. Take a deep breath. "
            "Your health and peace of mind come before any work. "
            "Would you like me to guide you through a quick breathing exercise, play relaxing music, or dim the display?"
        )
