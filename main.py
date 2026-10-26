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
        text_extensions = {
            ".txt", ".md", ".rst", ".log", ".csv", ".tsv", ".json", ".yaml", ".yml",
            ".xml", ".html", ".htm", ".py", ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp",
            ".java", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".kts", ".m",
            ".mm", ".r", ".scala", ".pl", ".pm", ".sh", ".bash", ".zsh", ".fish", ".bat",
            ".cmd", ".ps1", ".sql", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".css",
            ".scss", ".sass", ".less", ".toml", ".ini", ".cfg", ".conf", ".env", ".diff",
            ".patch", ".gradle", ".cmake", ".make", ".dockerfile", ".makefile", ".tex",
            ".bib", ".rtf", ".v", ".sv", ".vhdl", ".asm", ".s", ".lua", ".dart"
        }
        if suffix in text_extensions or path.name.lower() in ("dockerfile", "makefile", "cmakelists.txt", "gemfile", "pipfile", "requirements.txt", ".gitignore"):
            with path.open("r", encoding="utf-8", errors="replace") as stream:
                content = stream.read(250_000)
        elif suffix == ".pdf":
            from pypdf import PdfReader
            content = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages[:10])
        elif suffix in {".docx", ".doc"}:
            from docx import Document
            content = "\n".join(p.text for p in Document(str(path)).paragraphs)
        elif suffix in {".xlsx", ".xls", ".ods"}:
            import pandas as pd
            try:
                dfs = pd.read_excel(str(path), sheet_name=None)
                sheets_text = []
                for s_name, df in list(dfs.items())[:5]:
                    sheets_text.append(f"Sheet: {s_name}\n" + df.head(50).to_string())
                content = "\n\n".join(sheets_text)
            except Exception as e:
                content = f"Excel extract notice: {e}"
        elif suffix in {".pptx", ".ppt"}:
            from pptx import Presentation
            deck = Presentation(str(path))
            content = "\n".join(shape.text for slide in deck.slides for shape in slide.shapes if getattr(shape, "has_text_frame", False))
        elif suffix in {".zip", ".tar", ".gz", ".bz2", ".xz", ".7z"}:
            import zipfile, tarfile
            listing = []
            try:
                if zipfile.is_zipfile(str(path)):
                    with zipfile.ZipFile(str(path), 'r') as z:
                        listing = z.namelist()[:50]
                elif tarfile.is_tarfile(str(path)):
                    with tarfile.open(str(path), 'r') as t:
                        listing = t.getnames()[:50]
                content = f"Archive contents ({len(listing)} files shown):\n" + "\n".join(listing)
            except Exception as e:
                content = f"Archive reading note: {e}"
        elif suffix in {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".opus", ".wma"}:
            from faster_whisper.audio import decode_audio
            from core.stt import WhisperSTT
            stt = WhisperSTT(model_name="base.en", language="en")
            audio = decode_audio(str(path), sampling_rate=16000)
            content = "Audio transcript: " + (stt.transcribe(audio) or "No speech was detected.")
        elif suffix in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
            # Video attachment analysis: extract keyframes and audio transcript
            keyframes_summary = []
            import cv2
            cap = cv2.VideoCapture(str(path))
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            duration_sec = total_frames / fps if total_frames > 0 else 0
            keyframes_summary.append(f"Video duration: {duration_sec:.1f}s, {total_frames} frames.")
            # Extract 3-4 representative frames evenly spaced
            if total_frames > 0:
                import PIL.Image
                import io
                import base64
                step = max(1, total_frames // 4)
                extracted_images = []
                for f_idx in range(step // 2, total_frames, step)[:4]:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        pil_img = PIL.Image.fromarray(rgb)
                        pil_img.thumbnail((768, 768))
                        buf = io.BytesIO()
                        pil_img.save(buf, format="JPEG", quality=80)
                        extracted_images.append(buf.getvalue())
                cap.release()
                
                # Analyze keyframes with Gemini if key available
                cfg = _load_config() if "_load_config" in globals() else {}
                if not cfg:
                    try:
                        from core.llm_client import _load_config as _lc
                        cfg = _lc()
                    except Exception:
                        cfg = {}
                api_key = (cfg.get("gemini_api_key") or cfg.get("api_key") or "").strip()
                if api_key and extracted_images:
                    try:
                        from google import genai
                        from google.genai import types as gtypes
                        client = genai.Client(api_key=api_key)
                        parts = [gtypes.Part.from_bytes(data=img_bytes, mime_type="image/jpeg") for img_bytes in extracted_images]
                        parts.append(instruction or "Describe the visual contents and actions in this video sequence.")
                        for v_model in ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-flash-latest"]:
                            try:
                                resp = client.models.generate_content(
                                    model=v_model,
                                    contents=parts,
                                    http_options=gtypes.HttpOptions(timeout=20_000),
                                )
                                if resp.text:
                                    keyframes_summary.append("Visual Analysis:\n" + resp.text.strip())
                                    break
                            except Exception:
                                continue
                    except Exception as g_err:
                        keyframes_summary.append(f"Visual processing note: {g_err}")
            else:
                cap.release()

            # Also transcribe audio from video if possible
            try:
                from faster_whisper.audio import decode_audio
                from core.stt import WhisperSTT
                stt = WhisperSTT(model_name="tiny")
                audio = decode_audio(str(path), sampling_rate=16000)
                trans = stt.transcribe(audio)
                if trans and trans.strip():
                    keyframes_summary.append(f"Audio Dialogue: {trans.strip()}")
            except Exception:
                pass
            content = "\n".join(keyframes_summary)
        elif suffix in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}:
            import base64
            import io
            from PIL import Image

            # Check if Gemini key is available for ultra-fast (sub-second) multimodal vision
            cfg = {}
            try:
                from core.llm_client import _load_config as _lc
                cfg = _lc()
            except Exception:
                pass
            api_key = (cfg.get("gemini_api_key") or cfg.get("api_key") or "").strip()
            img_bytes = path.read_bytes()

            # Resize image if excessive
            try:
                pil_im = Image.open(io.BytesIO(img_bytes))
                if pil_im.width > 1280 or pil_im.height > 1280:
                    pil_im.thumbnail((1280, 1280))
                    buf = io.BytesIO()
                    pil_im.save(buf, format="JPEG", quality=85)
                    img_bytes = buf.getvalue()
            except Exception:
                pass

            mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(suffix, "image/jpeg")
            content = ""
            if api_key:
                for v_model in ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-flash-latest"]:
                    try:
                        from google import genai
                        from google.genai import types as gtypes
                        client = genai.Client(api_key=api_key)
                        resp = client.models.generate_content(
                            model=v_model,
                            contents=[
                                gtypes.Part.from_bytes(data=img_bytes, mime_type=mime),
                                instruction or "Describe this image in clear detail."
                            ],
                            http_options=gtypes.HttpOptions(timeout=20_000),
                        )
                        content = (resp.text or "").strip()
                        if content:
                            break
                    except Exception as g_err:
                        continue
            else:
                content = ""

            # Fallback to local model if Gemini not configured or failed
            if not content:
                import requests
                local, url, model, provider = _local_model_config()
                if local:
                    encoded = base64.b64encode(img_bytes).decode("ascii")
                    try:
                        if provider == "ollama":
                            payload = {"model": model, "stream": False, "messages": [{"role": "user", "content": instruction, "images": [encoded]}], "options": {"num_predict": 180}}
                            response = requests.post(f"{url}/api/chat", json=payload, timeout=20)
                            response.raise_for_status()
                            content = response.json().get("message", {}).get("content", "")
                        else:
                            payload = {"model": model, "messages": [{"role": "user", "content": [{"type": "text", "text": instruction}, {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}]}], "max_tokens": 180}
                            response = requests.post(f"{url}/v1/chat/completions", json=payload, timeout=20)
                            response.raise_for_status()
                            content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                    except Exception as loc_err:
                        content = f"Image analysis error: {loc_err}"
                else:
                    content = "Image analysis requires either a configured Gemini API key or a local vision model."
        else:
            # Universal fallback: try reading as text or extracting strings
            try:
                with path.open("r", encoding="utf-8", errors="ignore") as stream:
                    content = stream.read(250_000)
            except Exception:
                try:
                    raw_bytes = path.read_bytes()[:100_000]
                    import re as _re
                    ascii_strings = _re.findall(b"[\x20-\x7E]{4,}", raw_bytes)
                    content = "Extracted file strings:\n" + "\n".join(s.decode("ascii", errors="ignore") for s in ascii_strings[:100])
                except Exception as e:
                    content = f"Binary file notice: {e}"
        content = (content or "No readable content found.")[:10000]
        attachment_cache[key] = content
        return content
    except Exception as exc:
        return f"Could not read this attachment locally: {exc}"

def main():
    ui = SamUI()
    cfg = _load_config()

    def write_log(msg: str):
        try:
            print(f"[SAM] {msg}", flush=True)
        except Exception:
            pass
        ui.write_log(msg)

    # Initialize TTS player if possible
    tts_player = None
    try:
        tts_player = create_tts_player(cfg)
    except Exception as e:
        write_log(f"SYS: TTS initialization warning: {e}")


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

    from memory.chat_history import save_message, load_messages
    chat_history = [(m.get("role", "User"), m.get("content", "")) for m in load_messages(limit=8)]

    def handle_text_command(cmd: str):
        cmd = cmd.strip()
        if not cmd:
            return
        
        ui.set_state("THINKING")
        ui.set_current_task(cmd[:14])
        
        try:
            # 1. Fast Path Intent Analyzer: run first so explicit actions (opening created projects, screen vision, music) are never blocked by lingering attachments
            from core.intent_analyzer import analyze_query_fast
            fast_content = analyze_query_fast(cmd, address=ui.form_of_address())

            attachment_paths = ui.selected_file_paths() if not fast_content else []
            analyze_attachments = bool(attachment_paths)
            local_model, model_url, _model_name, _provider = _local_model_config()
            privacy_blocked = False
            attached_context = ""
            if privacy_blocked:
                content = "For privacy, SAM did not send your attachments to the configured remote model. Select a model server running on this computer to analyze attached files."
                result = {"content": content, "backend": "privacy safeguard"}
                fast_content = None
            elif fast_content:
                write_log("SYS: Fast Intent Analyzer intercepted the query.")
                content = fast_content
                result = {"content": content, "backend": "fast_rules"}
            else:
                if analyze_attachments:
                    attachment_sections = []
                    remaining = 10000
                    for raw_path in attachment_paths[:10]:
                        file_path = Path(raw_path)
                        write_log(f"SYS: Reading attachment {file_path.name}…")
                        extracted = _extract_attachment(file_path, f"Read this image or file for the user's request: {cmd}")
                        section = f"Attached file: {file_path.name}\n{extracted[:remaining]}"
                        attachment_sections.append(section)
                        remaining -= len(section)
                        if remaining <= 0:
                            break
                    attached_context = "\n\n".join(attachment_sections)

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
                        write_log(f"SYS: Web search unavailable: {search_error}")
                        web_context = "Live web search is temporarily unavailable, so answer from your available knowledge and clearly say you could not verify current information."
                if web_context:
                    context_prompt = f"Live web search results (use when relevant and cite URLs):\n{web_context}\n\nUser request: {cmd}"
                if attached_context:
                    web_section = f"Live web search results:\n{web_context}\n\n" if web_context else ""
                    context_prompt = (
                        f"{attached_context}\n\n{web_section}User request: {cmd}\n"
                        f"If the attached file contains an actionable voice or written command (like 'open app', 'set reminder', etc.), "
                        f"emit the exact tool call format: <|tool_call>call:tool_name{{\"param\": \"value\"}}<tool_call|> so it executes immediately on the system. "
                        f"Answer directly using the attached file. Do not ask the user to repeat or specify the contents."
                    )
                if chat_history:
                    history_text = "\n".join(f"{role}: {msg[:600]}" for role, msg in chat_history[-4:])
                    context_prompt = f"Recent conversation context:\n{history_text}\n\n{context_prompt}"
                    
                long_answer = any(word in cmd.lower() for word in ("explain in detail", "step by step", "comprehensive", "write a report", "write an essay", "plan", "what do you do", "who are you", "what can you do"))
                token_limit = 2048 if long_answer else 1200
                address = ui.form_of_address()
                addressed_system = (
                    f"{system_prompt}\n"
                    f"CRITICAL SALUTATION INSTRUCTION: The user MUST be addressed ONLY as '{address}'. "
                    f"NEVER refer to the user as 'sir' under any circumstances when addressing as '{address}'. "
                    f"Do not mix 'sir' and '{address}' in the same answer."
                )
                if analyze_attachments:
                    # Use brain_router (Gemini/cloud) first for instant response, fall back to local model if offline
                    try:
                        result = call_brain(prompt=context_prompt, system=addressed_system, task_type="auto", timeout=30, max_tokens=token_limit)
                    except Exception as b_err:
                        from core.llm_client import call_llm_text
                        result = {"content": call_llm_text(context_prompt, system=addressed_system, timeout=60, max_tokens=token_limit), "backend": "local model"}
                else:
                    try:
                        result = call_brain(prompt=context_prompt, system=addressed_system, task_type="auto", max_tokens=token_limit)
                    except Exception as b_err:
                        from core.llm_client import call_llm_text
                        result = {"content": call_llm_text(context_prompt, system=addressed_system, timeout=60, max_tokens=token_limit), "backend": "local model"}
                content = result.get("content", "").strip()
            
            backend = result.get("backend", "brain") if not fast_content else "fast_rules"
            
            if "<|tool_call>" in content:
                import re
                import importlib
                match = re.search(r"<\|tool_call>call:([a-zA-Z_0-9]+)\s*(.*?)\s*<tool_call\|>", content, re.DOTALL)
                if not match:
                    match = re.search(r"<\|tool_call>call:([a-zA-Z_0-9]+)\s*[\{\(](.*?)(?:[\}\)]\s*<tool_call\|>|[\}\)]\s*```|[\}\)])", content, re.DOTALL)
                if not match:
                    match = re.search(r"<\|tool_call>call:([a-zA-Z_0-9]+)\s*(.*)", content, re.DOTALL)
                if match:
                    t_name = match.group(1)
                    raw_args = match.group(2).strip().replace('<|"|>', '"')
                    # Strip outer parens or markdown fences
                    raw_args = re.sub(r"^\(+|\)+$", "", raw_args).strip()
                    while raw_args.startswith("{{") and raw_args.endswith("}}"):
                        raw_args = raw_args[1:-1].strip()
                    if not (raw_args.startswith("{") and raw_args.endswith("}")):
                        raw_args = "{" + raw_args.strip("{}") + "}"
                    try:
                        import json
                        t_args_dict = json.loads(raw_args)
                    except Exception:
                        clean_str = raw_args.strip("{}").strip()
                        t_args_dict = {}
                        if ":" in clean_str:
                            try:
                                import ast
                                t_args_dict = ast.literal_eval("{" + clean_str + "}")
                            except Exception:
                                pass
                        if not t_args_dict and "=" in clean_str:
                            try:
                                key, val = clean_str.split("=", 1)
                                t_args_dict[key.strip()] = val.strip().strip('"').strip("'")
                            except Exception:
                                pass
                        if not t_args_dict:
                            t_args_dict = {"query": clean_str, "app_name": clean_str, "action": clean_str, "song": clean_str}

                    # Instant voice acknowledgement for long-running tools
                    address = ui.form_of_address()
                    quick_acks = {
                        "autonomous_task": f"Right away, {address}. Initializing your overnight autonomous project.",
                        "dev_agent": f"On it, {address}. Checking the project files now.",
                        "screen_processor": f"Checking your display now, {address}.",
                        "file_controller": f"Accessing your files now, {address}.",
                        "browser_control": f"Opening browser now, {address}.",
                    }
                    if t_name in quick_acks:
                        speak_text(quick_acks[t_name])

                    try:
                        write_log(f"SYS: Executing tool {t_name}...")
                        if t_name == "set_salutation":
                            sal = t_args_dict.get("salutation", "Sir")
                            other = t_args_dict.get("other_name", "")
                            new_addr = ui.set_salutation(sal, other)
                            content = f"Understood, {new_addr}. I have updated my protocol and will address you as {new_addr} from now on."
                            speak_text(content)
                            write_log(f"SAM: {content}")
                            ui.set_state("LISTENING")
                            ui.set_current_task("IDLE")
                            return
                        if t_name == "sleep_mode":
                            ui.set_wake_state("SLEEPING")
                            content = "Entering standby sleep mode. You can wake me anytime by saying 'Hey Sam' or pressing Option+F5."
                            speak_text(content)
                            write_log(f"SAM: {content}")
                            ui.set_state("LISTENING")
                            ui.set_current_task("IDLE")
                            return
                        if t_name in ("chat_history", "show_chat_history", "previous_chats"):
                            ui.show_chat_history()
                            from memory.chat_history import get_recent_summary
                            recent = get_recent_summary(max_turns=3)
                            content = f"Displaying previous conversation transcripts, {address}."
                            speak_text(f"Displaying previous conversation transcripts, {address}.")
                            write_log(f"SAM: {content}\n{recent}")
                            ui.set_state("LISTENING")
                            ui.set_current_task("IDLE")
                            return
                        if t_name == "shutdown_sam":
                            content = "Powering down SAM subsystems. Have a wonderful day."
                            speak_text(content)
                            write_log(f"SAM: {content}")
                            return

                        alias_map = {
                            "screen_process": "screen_processor",
                            "screen_processor": "screen_processor",
                            "system_monitor": "system_status",
                            "system_status": "system_status",
                            "youtube": "youtube_video",
                            "youtube_video": "youtube_video",
                            "open_created_project": "dev_agent",
                            "weather_action": "weather_report",
                            "weather_report": "weather_report",
                            "weather": "weather_report",
                        }
                        resolved_name = alias_map.get(t_name, t_name)
                        mod = importlib.import_module(f"actions.{resolved_name}")
                        if t_name == "open_created_project" and hasattr(mod, "open_created_project"):
                            func = getattr(mod, "open_created_project")
                        else:
                            func = getattr(mod, resolved_name, getattr(mod, t_name, getattr(mod, "weather_action", None)))
                        if func is None:
                            raise AttributeError(f"No executable function for tool '{t_name}' in actions.{resolved_name}")
                        t_res = func(t_args_dict)

                        # Direct return for clean tools to eliminate double-LLM latency
                        direct_tools = {
                            "open_app", "autonomous_task", "background_monitor", "dev_agent",
                            "code_helper", "file_controller", "computer_settings", "system_status",
                            "reminder", "phone_notifier", "emotional_support",
                            "screen_processor", "screen_process", "youtube_video", "open_created_project",
                            "weather_report", "weather_action", "flight_finder", "game_updater",
                            "file_processor", "computer_control", "send_message"
                        }
                        if t_name in direct_tools or resolved_name in direct_tools:
                            content = str(t_res).strip() or f"{t_name} completed, {address}."
                        else:
                            # Tool output summarization only for raw web/browser output
                            try:
                                feedback_prompt = f"Original user query: {cmd}\nTool {t_name} output:\n{t_res}\n\nPlease summarize the output naturally for the user."
                                address = ui.form_of_address()
                                addressed_system = (
                                    f"{system_prompt}\n"
                                    f"CRITICAL SALUTATION INSTRUCTION: The user MUST be addressed ONLY as '{address}'. "
                                    f"NEVER refer to the user as 'sir' under any circumstances when addressing as '{address}'. "
                                    f"Do not mix 'sir' and '{address}' in the same answer."
                                )
                                res2 = call_brain(prompt=feedback_prompt, system=addressed_system, task_type="auto", max_tokens=1000)
                                content = (res2.get("content", "") or "").strip() or str(t_res).strip()
                            except Exception:
                                content = str(t_res).strip()
                    except Exception as e:
                        content = f"SYS: Tool execution failed ({t_name}): {e}"

            if "<|tool_call>" in content:
                import re
                content = re.sub(r"<\|tool_call>.*?<tool_call\|>", "", content, flags=re.DOTALL).strip()
                if not content:
                    content = f"Action completed, {ui.form_of_address()}."

            # Dynamic salutation filter so any tool returning 'sir' or LLM text conforms to chosen title
            current_addr = ui.form_of_address()
            if current_addr and current_addr.lower() != "sir":
                import re
                content = re.sub(r',\s*[Ss]ir\b', f', {current_addr}', content)
                content = re.sub(r'\b[Ss]ir([.!?:]|\s*$)', rf'{current_addr}\1', content)
                content = re.sub(r'^[Ss]ir([,!:;])', rf'{current_addr}\1', content)

            write_log(f"SAM: {content}")
            
            # Store in short-term memory & persistent disk storage
            chat_history.append(("User", cmd))
            save_message("User", cmd)
            # Strip tool calls from history so the bot doesn't repeat them
            clean_content = content
            if "<|tool_call>" in clean_content:
                import re
                clean_content = re.sub(r"<\|tool_call>.*<tool_call\|>", "", clean_content).strip()
            final_sam_text = clean_content or "Tool executed successfully."
            chat_history.append(("SAM", final_sam_text))
            save_message("SAM", final_sam_text)
            
            ui.set_state("LISTENING")
            ui.set_current_task("IDLE")
            
            # Speak the response
            speak_text(content)
        except Exception as e:
            err_msg = f"SYS: Error processing command: {e}"
            write_log(err_msg)
            fallback_msg = "I encountered a momentary issue processing that request. Please try again or rephrase."
            write_log(f"SAM: {fallback_msg}")
            speak_text(fallback_msg)
            ui.set_state("LISTENING")
            ui.set_current_task("IDLE")

    def handle_interrupt():
        if tts_player and tts_player.is_playing:
            tts_player.stop()
        ui.set_state("LISTENING")
        ui.set_current_task("IDLE")

    wake_enabled = bool(cfg.get("wake_word_enabled", True))
    clap_enabled = bool(cfg.get("clap_to_wake_enabled", True))
    audio_state = {
        "recording": False, "buffer": [], "command_mode": False,
        "last_voice": 0.0, "wake_enabled": wake_enabled, "clap_enabled": clap_enabled,
    }

    def _transcribe_and_run(audio_data):
        def _transcribe():
            try:
                if not hasattr(main, "stt"):
                    from core.stt import WhisperSTT
                    main.stt = WhisperSTT(model_name="tiny.en", language="en")
                text = main.stt.transcribe(audio_data)
                if text and text.strip():
                    clean_text = text.strip()
                    ui.set_wake_state("LISTENING")
                    write_log(f"You (Voice): {clean_text}")
                    handle_text_command(clean_text)
                else:
                    write_log("SYS: No speech detected.")
            except Exception as e:
                write_log(f"SYS: Voice transcription error: {e}")
        threading.Thread(target=_transcribe, daemon=True).start()
    
    def handle_mic_toggle(is_muted: bool):
        if not is_muted:
            if audio_state.get("recording", False):
                return
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
                            write_log('SYS: Loading on-device English "Hey Sam" voice recognition (base.en)…')
                            main.stt = WhisperSTT(model_name="base.en", language="en")
                        whisper = main.stt
                    except Exception as e:
                        write_log(f"SYS: Wake phrase unavailable: {e}")

                from core.wake_word import ClapDetector

                def _on_clap_woken():
                    if audio_state.get("command_mode", False):
                        return
                    now = time.monotonic()
                    audio_state["command_mode"] = True
                    audio_state["command_start"] = now
                    audio_state["buffer"] = []
                    audio_state["last_voice"] = now
                    audio_state["spoke_in_command"] = False
                    ui.set_wake_state("COMMAND")
                    write_log('SYS: 👏 Double clap detected! Waking SAM. Listening for your command…')

                clap_detector = ClapDetector(on_wake=_on_clap_woken)
                zero_chunk_count = 0
                if sys.platform == "darwin":
                    try:
                        import AVFoundation
                        auth = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(AVFoundation.AVMediaTypeAudio)
                        if auth == 2: # Denied
                            write_log("SYS: ⚠️ Microphone permission is DENIED in macOS System Settings. Please allow Python/Terminal under Privacy & Security -> Microphone.")
                    except Exception:
                        pass
                try:
                    with sd.InputStream(samplerate=16000, channels=1, dtype='float32') as stream:
                        write_log("SYS: Audio stream connected to microphone.")
                        while audio_state["recording"]:
                            chunk, _overflow = stream.read(4000)
                            if not len(chunk):
                                continue
                            samples = chunk.reshape(-1).copy()
                            rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
                            if rms == 0.0:
                                zero_chunk_count += 1
                                if zero_chunk_count == 25:
                                    write_log("SYS: ⚠️ Microphone receiving silence (RMS=0.0). Check macOS Privacy & Security -> Microphone permissions.")
                            else:
                                zero_chunk_count = 0
                            
                            # Live visual feedback on HUD mic level bar
                            try:
                                ui.set_mic_level(min(1.0, rms * 15.0))
                            except Exception:
                                pass

                            # Echo suppression: ignore microphone input while SAM is actively speaking
                            if tts_player and getattr(tts_player, "is_playing", False):
                                wake_frames.clear()
                                wake_samples = 0
                                wake_check_samples = 0
                                clap_detector.reset()
                                if audio_state["command_mode"]:
                                    audio_state["buffer"] = []
                                    audio_state["last_voice"] = time.monotonic()
                                continue

                            # Clap-to-wake detection when not in command mode
                            if audio_state.get("clap_enabled", True) and not audio_state["command_mode"]:
                                pcm_int16 = (samples * 32767.0).clip(-32768, 32767).astype(np.int16)
                                clap_detector.process_chunk(pcm_int16)

                            if not audio_state["wake_enabled"] or whisper is None:
                                audio_state["buffer"].append(samples)
                                continue

                            if audio_state["command_mode"]:
                                audio_state["buffer"].append(samples)
                                now = time.monotonic()
                                # Detect speech above ambient noise floor
                                speech_threshold = max(0.005, audio_state.get("noise_floor", 0.004) * 1.5)
                                if rms >= speech_threshold:
                                    audio_state["last_voice"] = now
                                    audio_state["spoke_in_command"] = True
                                
                                buffer_samples = sum(len(p) for p in audio_state["buffer"])
                                # Wait for 3.0 seconds of silence after user spoke, or max 30s timeout
                                if audio_state.get("spoke_in_command", False) and buffer_samples >= 16000 and (now - audio_state["last_voice"] >= 3.0):
                                    captured = np.concatenate(audio_state["buffer"])
                                    audio_state["buffer"] = []
                                    audio_state["command_mode"] = False
                                    audio_state["spoke_in_command"] = False
                                    wake_frames.clear()
                                    wake_samples = 0
                                    wake_check_samples = 0
                                    ui.set_wake_state("LISTENING")
                                    _transcribe_and_run(captured)
                                elif now - audio_state.get("command_start", now) >= 30.0:
                                    # Command timeout: 30 seconds limit
                                    if audio_state.get("spoke_in_command", False) and buffer_samples >= 16000:
                                        captured = np.concatenate(audio_state["buffer"])
                                        audio_state["buffer"] = []
                                        audio_state["command_mode"] = False
                                        audio_state["spoke_in_command"] = False
                                        wake_frames.clear()
                                        wake_samples = 0
                                        wake_check_samples = 0
                                        ui.set_wake_state("LISTENING")
                                        _transcribe_and_run(captured)
                                    else:
                                        write_log("SYS: Command listening timed out (30s). Ready for 'Hey Sam'.")
                                        audio_state["buffer"] = []
                                        audio_state["command_mode"] = False
                                        audio_state["spoke_in_command"] = False
                                        wake_frames.clear()
                                        wake_samples = 0
                                        wake_check_samples = 0
                                        ui.set_wake_state("LISTENING")
                                continue

                            # Update rolling noise floor estimate during quiet listening
                            current_floor = audio_state.get("noise_floor", 0.003)
                            audio_state["noise_floor"] = current_floor * 0.95 + min(rms, 0.02) * 0.05

                            wake_frames.append(samples)
                            wake_samples += len(samples)
                            wake_check_samples += len(samples)
                            while wake_samples > 48000 and wake_frames:
                                wake_samples -= len(wake_frames.pop(0))
                            
                            # Check every ~0.375s (6000 samples) once we have at least ~0.8s (12000 samples) of audio
                            if wake_samples >= 12000 and wake_check_samples >= 6000:
                                wake_check_samples = 0
                                # Transcribe wake buffer with vad_filter=False so short 'Hey Sam' is never suppressed
                                phrase = whisper.transcribe(np.concatenate(wake_frames), vad_filter=False).lower().strip()

                                # Match "hey sam", "hi sam", "hello sam", "ok sam", "sam"
                                match = re.search(r"\b(?:hey|hi|hello|ok|hye)?[\s,.]*\b(?:sam|sem)\b", phrase, re.IGNORECASE)
                                if match:
                                    command_tail = phrase[match.end():].strip(" ,.!?\n")
                                    wake_frames.clear()
                                    wake_samples = 0
                                    wake_check_samples = 0

                                    # Only execute directly if user spoke a full multi-word command in one breath
                                    tail_words = command_tail.split()
                                    if len(tail_words) >= 3:
                                        write_log(f"You (Wake): Hey Sam, {command_tail}")
                                        threading.Thread(target=handle_text_command, args=(command_tail,), daemon=True).start()
                                    else:
                                        # Otherwise enter dedicated command listening mode to cleanly record full command
                                        now = time.monotonic()
                                        audio_state["command_mode"] = True
                                        audio_state["command_start"] = now
                                        audio_state["buffer"] = []
                                        audio_state["last_voice"] = now
                                        audio_state["spoke_in_command"] = False
                                        ui.set_wake_state("COMMAND")
                                        write_log('SYS: "Hey Sam" detected. Listening for your command…')
                except Exception as e:
                    write_log(f"SYS: Audio input error: {e}")
            threading.Thread(target=_record_loop, daemon=True).start()
        else:
            audio_state["recording"] = False
            try:
                ui.set_mic_level(0.0)
            except Exception:
                pass
            if audio_state["buffer"]:
                write_log("SYS: Transcribing voice...")
                import numpy as np
                audio_data = np.concatenate(audio_state["buffer"]).flatten()
                _transcribe_and_run(audio_data)
            audio_state["buffer"] = []
            audio_state["command_mode"] = False
            ui.set_wake_state("LISTENING")

    def handle_wake_trigger():
        import time
        now = time.monotonic()
        audio_state["command_mode"] = True
        audio_state["command_start"] = now
        audio_state["buffer"] = []
        audio_state["last_voice"] = now
        audio_state["spoke_in_command"] = False
        ui.set_wake_state("COMMAND")
        write_log('[Option+F5] "Hey Sam" manual trigger. Listening for your command…')

    def handle_clap_toggle(enabled: bool):
        audio_state["clap_enabled"] = enabled

    ui.on_text_command = handle_text_command
    ui.on_interrupt = handle_interrupt
    ui.on_mic_toggle = handle_mic_toggle
    ui.on_wake_trigger = handle_wake_trigger
    ui.on_clap_toggle = handle_clap_toggle
    if wake_enabled:
        # Start the wake listener at launch; the active mic indicator is already visible.
        handle_mic_toggle(False)

    write_log("SYS: Quantum neural matrix initialized.")
    write_log("SYS: MARK XLIX online. All telemetry nominal.")
    ui.set_state("LISTENING")
    ui.set_wake_state("LISTENING" if wake_enabled else "OFF")
    ui.set_current_task("IDLE")

    ui.run()

if __name__ == "__main__":
    main()
