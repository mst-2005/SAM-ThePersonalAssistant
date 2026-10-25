"""
Hybrid brain router for SAM.

Routes each text-reasoning request to the backend best suited for it:

  1. Complex tasks (coding, planning, research, long-form writing)
       → Gemini (SAM's primary complex-task brain — same key already used
         for voice, no extra setup needed)
       → optionally upgraded to GPT-5 (OpenAI cloud) instead, if
         "openai_api_key" is set in config/api_keys.json — skipped
         entirely (no wasted attempt) when no key is configured
  2. Simple/fast/offline tasks
       → local Hermes model via Ollama (core.llm_client), so quick
         commands never wait on a network round-trip
  3. Last resort: if Gemini/OpenAI both fail for a complex task, falls
       through to local Ollama too, so a request never just errors out
       with nothing to say.

This module does NOT touch the real-time voice loop — main.py still
talks to Gemini Live directly for that. This router is for background/
text reasoning, currently used by the `agent_task` tool.

Setup:
  - Local (Hermes via Ollama): already works if Ollama is installed and
    a model is pulled. Configure the exact model tag with "llm_model"
    in config/api_keys.json if it isn't "hermes3".
  - Cloud (Gemini): works out of the box — reuses the same Gemini key
    SAM already has for voice.
  - Cloud (GPT-5, optional): add "openai_api_key" (and optionally
    "openai_model", default "gpt-5") to config/api_keys.json to use it
    instead of Gemini for complex tasks. Entirely optional — SAM runs
    fully on Gemini + Hermes with no OpenAI key at all.

NOTE ON MODEL NAMING: OpenAI's model lineup moves fast. If "gpt-5"
ever stops resolving, check https://platform.openai.com/docs/models
for the current flagship name and update "openai_model".
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import requests

from core import llm_client

BASE_DIR    = llm_client.BASE_DIR
CONFIG_PATH = llm_client.CONFIG_PATH

# Lightweight heuristic — no LLM call needed just to decide which LLM to call.
_COMPLEX_MARKERS = re.compile(
    r"\b("
    r"code|debug|program|script|function|class\b|algorithm|refactor|"
    r"architecture|plan|research|analy[sz]e|design|write a|build a|"
    r"report|essay|explain in detail|compare|strategy|dataset|train(ing)?|"
    r"model\b|project"
    r")\b",
    re.IGNORECASE,
)

DEFAULT_OPENAI_MODEL = "gpt-5"


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def classify_task(prompt: str) -> str:
    """Returns 'complex' or 'simple'.

    Complex → routed to the cloud brain (GPT-5, falling back to Gemini).
    Simple  → routed straight to the local Hermes model for speed.
    """
    if len(prompt) > 220:
        return "complex"
    return "complex" if _COMPLEX_MARKERS.search(prompt) else "simple"


def _call_openai_cloud(prompt: str, system: Optional[str], timeout: int) -> str:
    cfg = _load_config()
    api_key = (cfg.get("openai_api_key") or "").strip()
    if not api_key:
        raise RuntimeError("no OpenAI API key configured")
    model = cfg.get("openai_model", DEFAULT_OPENAI_MODEL)

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "messages": messages},
        timeout=timeout,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return (content or "").strip()


def _call_gemini_text(prompt: str, system: Optional[str], timeout: int) -> str:
    """Text-only Gemini fallback — reuses SAM's existing Gemini key, no live session."""
    from google import genai
    from google.genai import types

    cfg = _load_config()
    api_key = (cfg.get("api_key") or cfg.get("gemini_api_key") or "").strip()
    if not api_key:
        raise RuntimeError("no Gemini API key configured")

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=min(timeout, 30) * 1000)
    )
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    preferred = cfg.get("gemini_model", "gemini-3.5-flash")
    candidates = [preferred, "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash"]
    seen = set()
    last_err = None
    for m in candidates:
        if m in seen:
            continue
        seen.add(m)
        try:
            resp = client.models.generate_content(
                model=m,
                contents=full_prompt,
            )
            text = (resp.text or "").strip()
            if text:
                return text
        except Exception as e:
            last_err = e
            continue
    raise last_err or RuntimeError("Gemini models failed to return content")


def call_brain(
    prompt: str,
    system: Optional[str] = None,
    task_type: str = "auto",
    timeout: int = 120,
    max_tokens: int = 600,
) -> dict:
    """
    Routes `prompt` based on network connectivity and server availability.
    If online: uses Gemini (or OpenAI if configured).
    If offline: uses local Ollama model.
    """
    errors: list[str] = []
    cfg = _load_config()

    # Fast check if local server is responsive before waiting timeout
    local_up = False
    try:
        url, _ = llm_client.get_llm_settings()
        provider = llm_client.get_llm_provider()
        ping_endpoint = f"{url}/api/tags" if provider == "ollama" else f"{url}/v1/models"
        local_up = requests.get(ping_endpoint, timeout=(1.0, 2.0)).status_code == 200
    except Exception:
        local_up = False

    # Ultra-fast internet check using local DNS resolver (takes < 1ms)
    online = False
    try:
        import socket
        socket.gethostbyname("google.com")
        online = True
    except OSError:
        pass

    has_gemini = bool((cfg.get("api_key") or cfg.get("gemini_api_key") or "").strip())
    has_openai = bool((cfg.get("openai_api_key") or "").strip())

    if online and (has_gemini or has_openai):
        # Cloud LLM: Fast, complete, unconstrained responses
        if has_openai:
            try:
                content = _call_openai_cloud(prompt, system, timeout)
                return {"content": content, "backend": "openai"}
            except Exception as e:
                errors.append(f"openai: {e}")

        if has_gemini:
            try:
                content = _call_gemini_text(prompt, system, timeout)
                return {"content": content, "backend": "gemini"}
            except Exception as e:
                errors.append(f"gemini: {e}")

    # Fallback to local model (LM Studio or Ollama)
    if local_up:
        try:
            content = llm_client.call_llm_text(prompt, system=system, timeout=timeout, max_tokens=max_tokens)
            if content:
                return {"content": content, "backend": "local"}
        except Exception as e:
            errors.append(f"local model: {e}")

    raise RuntimeError("All brain backends failed — " + " | ".join(errors))
