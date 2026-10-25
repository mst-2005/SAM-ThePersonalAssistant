"""
SAM Orchestrator & Entrypoint.
Binds UI, BrainRouter, TTS, and Actions.
"""
import sys
import threading
import time
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from ui import SamUI
from core.brain_router import call_brain
from core.tts import create_tts_player
from core.llm_client import _load_config

def main():
    ui = SamUI()
    cfg = _load_config()

    # Initialize TTS player if possible
    tts_player = None
    try:
        tts_player = create_tts_player(cfg)
    except Exception as e:
        ui.write_log(f"SYS: TTS initialization warning: {e}")


    # Load system prompt
    prompt_file = Path(__file__).resolve().parent / "core" / "prompt.txt"
    system_prompt = ""
    if prompt_file.exists():
        try:
            system_prompt = prompt_file.read_text(encoding="utf-8")
        except Exception:
            pass

    def speak_text(text: str):
        if not tts_player:
            return
        def _on_start():
            ui.set_state("SPEAKING")
        def _on_done():
            ui.set_state("LISTENING")
        threading.Thread(
            target=tts_player.speak,
            args=(text,),
            kwargs={"on_start": _on_start, "on_done": _on_done},
            daemon=True
        ).start()

    chat_history = []
    attachment_cache = {}

    def _local_model_config():
        import ipaddress
        from urllib.parse import urlparse
        from core import llm_client

        url, model = llm_client.get_llm_settings()
        host = (urlparse(url).hostname or "").lower()
        try:
            local = host == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = False
        return local, url, model, llm_client.get_llm_provider()

    def _extract_attachment(path: Path, instruction: str) -> str:
        """Read attachment contents locally; never upload them to a cloud model."""
        try:
            stat = path.stat()
            key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
            if key in attachment_cache:
                return attachment_cache[key]
            suffix = path.suffix.lower()
            if suffix in {".txt", ".md", ".rst", ".log", ".csv", ".tsv", ".json", ".yaml", ".yml", ".xml", ".html", ".htm", ".py", ".js", ".ts", ".tsx", ".jsx", ".css", ".sql", ".sh", ".toml"}:
                with path.open("r", encoding="utf-8", errors="replace") as stream:
                    content = stream.read(250_000)
            elif suffix == ".pdf":
                from pypdf import PdfReader
                content = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages[:6])
            elif suffix == ".docx":
                from docx import Document
                content = "\n".join(p.text for p in Document(str(path)).paragraphs)
            elif suffix == ".pptx":
                from pptx import Presentation
                deck = Presentation(str(path))
                content = "\n".join(shape.text for slide in deck.slides for shape in slide.shapes if getattr(shape, "has_text_frame", False))
            elif suffix in {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".opus", ".wma"}:
                from faster_whisper.audio import decode_audio
                from core.stt import WhisperSTT
                if not hasattr(main, "stt"):
                    main.stt = WhisperSTT(model_name="tiny")
                audio = decode_audio(str(path), sampling_rate=16000)
                content = "Audio transcript: " + (main.stt.transcribe(audio) or "No speech was detected.")
            elif suffix in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}:
                import base64
                import requests
                local, url, model, provider = _local_model_config()
                if not local:
                    return "Image analysis skipped because the configured model server is not local."
                if path.stat().st_size > 5_000_000:
                    return "Image is larger than the 5 MB local analysis limit."
                encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(suffix, "image/jpeg")
                if provider == "ollama":
                    payload = {"model": model, "stream": False, "messages": [{"role": "user", "content": instruction, "images": [encoded]}], "options": {"num_predict": 180}}
                    response = requests.post(f"{url}/api/chat", json=payload, timeout=45)
                    response.raise_for_status()
                    content = response.json().get("message", {}).get("content", "")
                else:
                    payload = {"model": model, "messages": [{"role": "user", "content": [{"type": "text", "text": instruction}, {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}]}], "max_tokens": 180}
                    response = requests.post(f"{url}/v1/chat/completions", json=payload, timeout=45)
                    response.raise_for_status()
                    content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            else:
                content = f"Attached file type {suffix or '(unknown)'} is not supported for text extraction."
            content = (content or "No readable content found.")[:3000]
            attachment_cache[key] = content
            return content
        except Exception as exc:
            return f"Could not read this attachment locally: {exc}"

    def handle_text_command(cmd: str):
        cmd = cmd.strip()
        if not cmd:
            return
        
        ui.set_state("THINKING")
        ui.set_current_task(cmd[:14])
        
        try:
            attachment_paths = ui.selected_file_paths()
            file_terms = ("file", "attachment", "attached", "document", "pdf", "image", "photo", "picture", "audio", "recording", "transcript", "these files", "this file", "this document", "summarize", "analyse", "analyze", "read this", "what is in")
            analyze_attachments = bool(attachment_paths and any(term in cmd.lower() for term in file_terms))
            local_model, model_url, _model_name, _provider = _local_model_config()
            privacy_blocked = bool(analyze_attachments and not local_model)
            attached_context = ""
            if privacy_blocked:
                content = "For privacy, SAM did not send your attachments to the configured remote model. Select a model server running on this computer to analyze attached files."
                result = {"content": content, "backend": "privacy safeguard"}
                fast_content = None
            else:
                attachment_sections = []
                remaining = 10000
                for raw_path in (attachment_paths[:10] if analyze_attachments else []):
                    file_path = Path(raw_path)
                    ui.write_log(f"SYS: Reading attachment {file_path.name}…")
                    extracted = _extract_attachment(file_path, f"Read this image for the user's request: {cmd}")
                    section = f"Attached file: {file_path.name}\n{extracted[:remaining]}"
                    attachment_sections.append(section)
                    remaining -= len(section)
                    if remaining <= 0:
                        break
                attached_context = "\n\n".join(attachment_sections)

            # 1. Fast Path Intent Analyzer
            from core.intent_analyzer import analyze_query_fast
            if analyze_attachments and not local_model:
                fast_content = None
            else:
                fast_content = analyze_query_fast(cmd) if not analyze_attachments else None
            
            if privacy_blocked:
                pass
            elif fast_content:
                ui.write_log("SYS: Fast Intent Analyzer intercepted the query.")
                content = fast_content
            else:
                # 2. Only search the web if explicitly requested
                context_prompt = cmd
                web_context = ""
                explicit_web_request = any(word in cmd.lower() for word in ("web", "internet", "online", "latest news", "current news", "today's news", "weather", "search web", "google"))
                if explicit_web_request:
                    try:
                        from actions.web_search import _web_scrape, _format_scraped
                        web_context = _format_scraped(cmd, _web_scrape(cmd, max_results=2))
                        if web_context.startswith("No results found"):
                            web_context = "Live web search returned no usable pages, so answer from available knowledge and state that current details could not be verified."
                    except Exception as search_error:
                        ui.write_log(f"SYS: Web search unavailable: {search_error}")
                        web_context = "Live web search is temporarily unavailable, so answer from your available knowledge and clearly say you could not verify current information."
                if web_context:
                    context_prompt = f"Live web search results (use when relevant and cite URLs):\n{web_context}\n\nUser request: {cmd}"
                if attached_context:
                    web_section = f"Live web search results:\n{web_context}\n\n" if web_context else ""
                    context_prompt = f"{attached_context}\n\n{web_section}User request: {cmd}\nAnswer directly using the attached file and relevant live findings. Do not ask the user to repeat or specify the contents."
                if chat_history:
                    history_text = "\n".join(f"{role}: {msg[:600]}" for role, msg in chat_history[-4:])
                    context_prompt = f"Recent conversation context:\n{history_text}\n\n{context_prompt}"
                    
                long_answer = any(word in cmd.lower() for word in ("explain in detail", "step by step", "comprehensive", "write a report", "write an essay", "plan"))
                if analyze_attachments:
                    from core.llm_client import call_llm_text
                    address = ui.form_of_address()
                    addressed_system = f"{system_prompt}\nAddress the user as {address}."
                    result = {"content": call_llm_text(context_prompt, system=addressed_system, timeout=90, max_tokens=480 if long_answer else 220), "backend": "local model"}
                else:
                    address = ui.form_of_address()
                    addressed_system = f"{system_prompt}\nAddress the user as {address}."
                    result = call_brain(prompt=context_prompt, system=addressed_system, task_type="auto", max_tokens=480 if long_answer else 220)
                content = result.get("content", "").strip()
            
            backend = result.get("backend", "brain") if not fast_content else "fast_rules"
            
            if "<|tool_call>" in content:
                import re
                import importlib
                match = re.search(r"<\|tool_call>call:([a-zA-Z_0-9]+)[\{\(](.*?)[\}\)]<tool_call\|>", content, re.DOTALL)
                if match:
                    t_name = match.group(1)
                    t_args = match.group(2).replace('<|"|>', '"')
                    try:
                        import json
                        t_args_dict = json.loads("{" + t_args + "}")
                    except Exception:
                        clean_str = t_args.strip().strip('"').strip("'")
                        t_args_dict = {}
                        if "=" in clean_str:
                            try:
                                key, val = clean_str.split("=", 1)
                                t_args_dict[key.strip()] = val.strip().strip('"').strip("'")
                            except:
                                pass
                        
                        if not t_args_dict:
                            t_args_dict = {"query": clean_str, "app_name": clean_str, "action": clean_str}

                    # Instant voice acknowledgement for long-running tools
                    quick_acks = {
                        "autonomous_task": "Right away, sir. Initializing your overnight autonomous project.",
                        "dev_agent": "On it, sir. Architecting and building the project now.",
                        "screen_processor": "Checking your display now, sir.",
                        "file_controller": "Accessing your files now, sir.",
                        "browser_control": "Opening browser now, sir.",
                    }
                    if t_name in quick_acks:
                        speak_text(quick_acks[t_name])

                    try:
                        ui.write_log(f"SYS: Executing tool {t_name}...")
                        alias_map = {
                            "screen_process": "screen_processor",
                            "screen_processor": "screen_processor",
                            "system_monitor": "system_status",
                            "system_status": "system_status",
                        }
                        resolved_name = alias_map.get(t_name, t_name)
                        mod = importlib.import_module(f"actions.{resolved_name}")
                        func = getattr(mod, resolved_name, getattr(mod, t_name, None))
                        if func is None:
                            raise AttributeError(f"No executable function for tool '{t_name}' in actions.{resolved_name}")
                        t_res = func(t_args_dict)
                        
                        # Direct return for clean tools to eliminate double-LLM latency
                        direct_tools = {"open_app", "autonomous_task", "background_monitor", "dev_agent", "code_helper", "file_controller", "computer_settings", "system_status", "reminder", "phone_notifier"}
                        if t_name in direct_tools:
                            content = str(t_res).strip() or f"{t_name} completed, sir."
                        else:
                            # Tool output summarization only for raw web/browser output
                            feedback_prompt = f"Original user query: {cmd}\nTool {t_name} output:\n{t_res}\n\nPlease summarize the output naturally for the user."
                            address = ui.form_of_address()
                            res2 = call_brain(prompt=feedback_prompt, system=f"{system_prompt}\nAddress the user as {address}.", task_type="auto", max_tokens=220)
                            content = (res2.get("content", "") or "").strip() or str(t_res).strip()
                    except Exception as e:
                        content = f"SYS: Tool execution failed ({t_name}): {e}"
            
            if "<|tool_call>" in content:
                import re
                content = re.sub(r"<\|tool_call>.*?<tool_call\|>", "", content, flags=re.DOTALL).strip()
                if not content:
                    content = "I couldn't process that request, sir. Please try again."
            ui.write_log(f"SAM: {content}")
            
            # Store in short-term memory
            chat_history.append(("User", cmd))
            # Strip tool calls from history so the bot doesn't repeat them
            clean_content = content
            if "<|tool_call>" in clean_content:
                import re
                clean_content = re.sub(r"<\|tool_call>.*<tool_call\|>", "", clean_content).strip()
            chat_history.append(("SAM", clean_content or "Tool executed successfully."))
            
            ui.set_state("LISTENING")
            ui.set_current_task("IDLE")
            
            # Speak the response
            speak_text(content)
        except Exception as e:
            err_msg = f"SYS: Error processing command: {e}"
            ui.write_log(err_msg)
            ui.set_state("LISTENING")
            ui.set_current_task("IDLE")

    def handle_interrupt():
        if tts_player and tts_player.is_playing:
            tts_player.stop()
        ui.set_state("LISTENING")
        ui.set_current_task("IDLE")

    # The active microphone listens locally for "Hey Sam" and then captures a
    # short voice command. Whisper runs on-device; no audio is sent to a server.
    wake_enabled = bool(cfg.get("wake_word_enabled", True))
    audio_state = {
        "recording": False, "buffer": [], "command_mode": False,
        "last_voice": 0.0, "wake_enabled": wake_enabled,
    }

    def _transcribe_and_run(audio_data):
        def _transcribe():
            try:
                if not hasattr(main, "stt"):
                    from core.stt import WhisperSTT
                    main.stt = WhisperSTT(model_name="tiny")
                text = main.stt.transcribe(audio_data)
                if text and text.strip():
                    ui.set_wake_state("LISTENING")
                    ui.write_log(f"You (Voice): {text}")
                    handle_text_command(text)
                else:
                    ui.write_log("SYS: No speech detected.")
            except Exception as e:
                ui.write_log(f"SYS: Voice transcription error: {e}")
        threading.Thread(target=_transcribe, daemon=True).start()
    
    def handle_mic_toggle(is_muted: bool):
        if not is_muted:
            audio_state["recording"] = True
            audio_state["buffer"] = []
            audio_state["command_mode"] = False
            audio_state["last_voice"] = 0.0
            
            def _record_loop():
                import sounddevice as sd
                import numpy as np
                import re
                whisper = None
                wake_frames = []
                wake_samples = 0
                wake_check_samples = 0
                if audio_state["wake_enabled"]:
                    try:
                        if not hasattr(main, "stt"):
                            from core.stt import WhisperSTT
                            ui.write_log('SYS: Loading on-device "Hey Sam" voice recognition…')
                            main.stt = WhisperSTT(model_name="tiny")
                        whisper = main.stt
                    except Exception as e:
                        ui.write_log(f"SYS: Wake phrase unavailable: {e}")
                try:
                    with sd.InputStream(samplerate=16000, channels=1, dtype='float32') as stream:
                        while audio_state["recording"]:
                            chunk, _overflow = stream.read(4000)
                            if not len(chunk):
                                continue
                            samples = chunk.reshape(-1).copy()
                            rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
                            if not audio_state["wake_enabled"] or whisper is None:
                                audio_state["buffer"].append(samples)
                                continue

                            if audio_state["command_mode"]:
                                audio_state["buffer"].append(samples)
                                if rms >= 0.003:
                                    audio_state["last_voice"] = time.monotonic()
                                elif (sum(len(part) for part in audio_state["buffer"]) >= 16000
                                      and time.monotonic() - audio_state["last_voice"] >= 1.2):
                                    captured = np.concatenate(audio_state["buffer"])
                                    audio_state["buffer"] = []
                                    audio_state["command_mode"] = False
                                    _transcribe_and_run(captured)
                                continue

                            wake_frames.append(samples)
                            wake_samples += len(samples)
                            wake_check_samples += len(samples)
                            while wake_samples > 48000 and wake_frames:
                                wake_samples -= len(wake_frames.pop(0))
                            if wake_samples >= 20000 and wake_check_samples >= 12000 and rms >= 0.002:
                                wake_check_samples = 0
                                phrase = whisper.transcribe(np.concatenate(wake_frames)).lower()
                                match = re.search(r"\b(?:hey|hi|hello|ok)?[,. ]*sam\b", phrase, re.IGNORECASE)
                                if match:
                                    command_tail = phrase[match.end():].strip(" ,.!?\n")
                                    wake_frames.clear()
                                    wake_samples = 0
                                    if command_tail and len(command_tail.split()) >= 1:
                                        ui.write_log(f"You (Wake): Hey Sam, {command_tail}")
                                        threading.Thread(target=handle_text_command, args=(command_tail,), daemon=True).start()
                                    else:
                                        audio_state["command_mode"] = True
                                        audio_state["buffer"] = []
                                        audio_state["last_voice"] = time.monotonic()
                                        ui.set_wake_state("COMMAND")
                                        ui.write_log('SYS: "Hey Sam" detected. Listening for your command…')
                except Exception as e:
                    ui.write_log(f"SYS: Audio input error: {e}")
            threading.Thread(target=_record_loop, daemon=True).start()
        else:
            audio_state["recording"] = False
            if audio_state["buffer"] and not audio_state["wake_enabled"]:
                ui.write_log("SYS: Transcribing voice...")
                import numpy as np
                audio_data = np.concatenate(audio_state["buffer"]).flatten()
                _transcribe_and_run(audio_data)
            audio_state["buffer"] = []
            audio_state["command_mode"] = False
            ui.set_wake_state("LISTENING")

    ui.on_text_command = handle_text_command
    ui.on_interrupt = handle_interrupt
    ui.on_mic_toggle = handle_mic_toggle
    if wake_enabled:
        # Start the wake listener at launch; the active mic indicator is already visible.
        handle_mic_toggle(False)

    ui.write_log("SYS: Quantum neural matrix initialized.")
    ui.write_log("SYS: MARK XLIX online. All telemetry nominal.")
    ui.set_state("LISTENING")
    ui.set_wake_state("LISTENING" if wake_enabled else "OFF")
    ui.set_current_task("IDLE")

    ui.run()

if __name__ == "__main__":
    main()
