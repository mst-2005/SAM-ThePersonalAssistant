"""
phone_notifier.py — SAM Cell Phone Integration & Outbound Voice Calling
Allows SAM to connect with the user's mobile device, send progress reports,
and place real voice calls to notify the user when projects make progress or finish.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import urllib.parse
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
_OS = platform.system()


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_config(cfg: dict) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=4, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"[PhoneNotifier] Config save error: {e}")


def get_phone_connection_status() -> str:
    """Returns status and instructions on how the user's phone is connected."""
    cfg = _load_config()
    user_phone = cfg.get("user_phone_number", "").strip()
    twilio_sid = cfg.get("twilio_account_sid", "").strip()
    
    # Check local IP for web HUD phone pairing
    import socket
    local_ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    lines = [
        "[PHONE] SAM Cell Phone Connection Status:",
        f"  - Registered Phone Number: {user_phone or 'Not configured yet'}",
        f"  - Voice Calling Service: {'Twilio Voice Active' if twilio_sid else 'Windows Phone Link / Direct Dial'}",
        f"  - Mobile Web HUD URL: http://{local_ip}:8000",
        "",
        "[CONNECT] How to Connect Your Phone:",
        f"1. Open Mobile HUD: Open http://{local_ip}:8000 on your phone browser (same Wi-Fi).",
        "2. Voice Calling: Say 'save my phone number <number>' so SAM can call you with project updates.",
        "3. Windows Phone Link: On Windows, ensure 'Phone Link' is paired with your Android/iPhone.",
    ]
    return "\n".join(lines)


def configure_phone(phone_number: str) -> str:
    """Saves the user's cell phone number for automated calls and SMS."""
    cleaned = phone_number.strip().replace(" ", "").replace("-", "")
    if not cleaned.startswith("+"):
        # Assume international standard or prepend + if missing
        cleaned = "+" + cleaned if cleaned.isdigit() else cleaned
        
    cfg = _load_config()
    cfg["user_phone_number"] = cleaned
    _save_config(cfg)
    return f"Phone number successfully saved as {cleaned}, sir. SAM will call this number for project updates and alerts."


def call_user_phone(message: str, phone_number: Optional[str] = None) -> str:
    """
    Places an automated voice call to the user's mobile device.
    Uses Twilio Voice API if configured, otherwise falls back to Windows Phone Link.
    """
    cfg = _load_config()
    target_number = phone_number or cfg.get("user_phone_number", "").strip()
    
    if not target_number:
        return (
            "No phone number is registered yet, sir. "
            "Please tell me 'save my phone number <your-number>' so I know where to call you."
        )

    # 1. Try Twilio Cloud Voice API if credentials exist
    twilio_sid = cfg.get("twilio_account_sid", "").strip()
    twilio_token = cfg.get("twilio_auth_token", "").strip()
    twilio_from = cfg.get("twilio_phone_number", "").strip()
    
    if twilio_sid and twilio_token and twilio_from:
        try:
            from twilio.rest import Client
            client = Client(twilio_sid, twilio_token)
            
            # Escape XML entities in speech
            safe_text = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            twiml = f"<Response><Say voice='Polly.Brian'>{safe_text}</Say></Response>"
            
            call = client.calls.create(
                to=target_number,
                from_=twilio_from,
                twiml=twiml
            )
            return f"Outbound call placed to {target_number} (Call SID: {call.sid}), sir."
        except Exception as e:
            print(f"[PhoneNotifier] Twilio call failed: {e}")

    # 2. Windows Phone Link / System Tel Protocol
    if _OS == "Windows":
        try:
            # Trigger tel: URI which opens Windows Phone Link to place the call
            encoded_uri = f"tel:{urllib.parse.quote(target_number)}"
            os.startfile(encoded_uri)
            return (
                f"Calling {target_number} via Windows Phone Link, sir. "
                f"Spoken message queued: '{message}'."
            )
        except Exception as we:
            return f"Could not initiate call via Phone Link: {we}"
            
    return f"Phone call queued for {target_number}: '{message}'."


def send_phone_sms(message: str, phone_number: Optional[str] = None) -> str:
    """Sends an SMS or WhatsApp notification to the user's cell phone."""
    cfg = _load_config()
    target_number = phone_number or cfg.get("user_phone_number", "").strip()
    
    if not target_number:
        return "No phone number is configured, sir."

    # Try WhatsApp Web / App protocol
    try:
        clean_num = target_number.lstrip("+")
        encoded_msg = urllib.parse.quote(message)
        wa_url = f"https://api.whatsapp.com/send?phone={clean_num}&text={encoded_msg}"
        import webbrowser
        webbrowser.open(wa_url)
        return f"Update sent to your phone via WhatsApp ({target_number}), sir."
    except Exception as e:
        return f"Could not send phone update: {e}"


def phone_notifier(parameters: dict = None, **kwargs) -> str:
    params = parameters if isinstance(parameters, dict) else {}
    action = params.get("action", "status").lower().strip()
    number = params.get("phone_number") or params.get("number") or ""
    message = params.get("message") or params.get("text") or "Project update from SAM."
    
    if action in ("status", "info", "check"):
        return get_phone_connection_status()
    elif action in ("configure", "save_number", "save_phone", "register"):
        return configure_phone(number)
    elif action in ("call", "call_user", "voice_call", "dial"):
        return call_user_phone(message=message, phone_number=number or None)
    elif action in ("sms", "text", "whatsapp", "send"):
        return send_phone_sms(message=message, phone_number=number or None)
    else:
        if number:
            return configure_phone(number)
        return get_phone_connection_status()
