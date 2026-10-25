"""
Text-to-Speech engines for MARK XL.

EdgeTTS     – free Microsoft TTS (internet required, no API key)
Kokoro      – fully offline neural TTS (~330 MB model)
ElevenLabs  – cloud API (API key required, best quality)
"""
from __future__ import annotations

import asyncio
import os
import platform
import queue as _queue
import shutil
import subprocess
import threading
from typing import Callable, Optional

import numpy as np
import sounddevice as sd



# USE_TF=0 stops transformers from importing TensorFlow (saves 4-8 s startup).
# Do NOT set USE_TORCH or USE_JAX explicitly — forcing those values breaks
# transformers' lazy-loader on certain versions, causing AutoModel and other
# classes to vanish from the public namespace.  Auto-detection is reliable.
os.environ.setdefault("USE_TF",                 "0")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


# ---------------------------------------------------------------------------
# Audio playback helpers
# ---------------------------------------------------------------------------

def _to_numpy(samples) -> np.ndarray:
    """Convert samples to float32 numpy array.

    Handles both numpy arrays and PyTorch tensors (Kokoro >= 0.9).

    PyTorch built against numpy 1.x raises RuntimeError('Numpy is not available')
    when numpy 2.x is installed.  The .tolist() fallback always works regardless
    of PyTorch / numpy version pairing.
    """
    if hasattr(samples, "detach"):                  # PyTorch tensor
        t = samples.detach().cpu().float()
        try:
            return t.numpy()                        # fast path (compatible versions)
        except RuntimeError:
            # PyTorch/numpy version mismatch — convert via Python list (always safe)
            return np.asarray(t.tolist(), dtype=np.float32)
    return np.asarray(samples, dtype=np.float32)


def _compress_silence(
    arr: np.ndarray,
    sample_rate: int    = 24_000,
    max_silence_ms: int = 500,    # cap punctuation pauses — keeps natural rhythm
    threshold: float    = 0.003,  # RMS below this = silence; lower = less clipping
) -> np.ndarray:
    """
    Shorten Kokoro's very long punctuation pauses (1-2 s → ≤500 ms).
    Conservative settings preserve natural prosody; only trims extreme pauses.
    """
    max_samp  = int(max_silence_ms * sample_rate / 1000)
    frame_len = 240                   # ~10 ms at 24 kHz
    out: list[np.ndarray] = []
    silent_acc = 0

    for i in range(0, len(arr), frame_len):
        chunk = arr[i : i + frame_len]
        if np.sqrt(np.mean(chunk ** 2) + 1e-12) < threshold:
            silent_acc += len(chunk)
            if silent_acc <= max_samp:
                out.append(chunk)
        else:
            silent_acc = 0
            out.append(chunk)

    return np.concatenate(out) if out else arr


def _play_np(samples, sample_rate: int) -> None:
    """Play float32 mono (or stereo) audio via sounddevice.
    Accepts numpy arrays or PyTorch tensors.
    """
    sd.play(_to_numpy(samples), sample_rate)
    sd.wait()


def _play_audio_bytes(audio_bytes: bytes) -> None:
    """Decode MP3/WAV/OGG bytes and play via sounddevice (uses miniaudio)."""
    import miniaudio
    decoded = miniaudio.decode(
        audio_bytes,
        output_format=miniaudio.SampleFormat.FLOAT32,
        nchannels=1,
    )
    samples = np.array(decoded.samples, dtype=np.float32)
    sd.play(samples, decoded.sample_rate)
    sd.wait()


# ---------------------------------------------------------------------------
# Engines
# ---------------------------------------------------------------------------

class EdgeTTSEngine:
    """Microsoft EdgeTTS – free, requires internet."""

    def __init__(self, voice: str = "en-US-AriaNeural"):
        self.voice = voice

    def speak(self, text: str) -> None:
        loop = asyncio.new_event_loop()
        try:
            audio_bytes = loop.run_until_complete(self._synth(text))
        finally:
            loop.close()
        if audio_bytes:
            _play_audio_bytes(audio_bytes)

    async def _synth(self, text: str) -> bytes:
        import edge_tts
        comm = edge_tts.Communicate(text, self.voice)
        buf  = bytearray()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                buf.extend(chunk["data"])
        return bytes(buf)


# ---------------------------------------------------------------------------
# Kokoro import helper — auto-upgrades on version-mismatch errors
# ---------------------------------------------------------------------------

# Errors that indicate the installed kokoro uses old transformers classes
# (AlbertModel, AutoModel) that are no longer exported at the top level.
_KOKORO_COMPAT_ERRORS = ("AlbertModel", "AutoModel", "cannot import name")


def _import_kokoro_pipeline():
    """Import KPipeline, auto-upgrading kokoro if a version mismatch is found.

    Old kokoro (<0.9) imports AlbertModel / AutoModel from transformers.
    Newer transformers versions no longer export these at the top level,
    causing an ImportError.  kokoro>=0.9 removed these dependencies.

    When the error is detected we:
      1. Upgrade kokoro to >=0.9 via pip (silent, background)
      2. Flush stale kokoro entries from sys.modules
      3. Re-import — this time it should succeed
    """
    import sys

    def _try_import():
        from kokoro import KPipeline  # noqa: PLC0415
        return KPipeline

    try:
        return _try_import()
    except Exception as first_err:
        err_msg = str(first_err)
        if not any(marker in err_msg for marker in _KOKORO_COMPAT_ERRORS):
            # Unrelated error (kokoro not installed, etc.)
            raise RuntimeError(
                f"Kokoro import failed: {first_err}\n"
                "Run: pip install kokoro>=0.9 soundfile"
            ) from first_err

        # ── Version mismatch: upgrade kokoro silently and retry ──────────
        print("[TTS] Kokoro/transformers version mismatch detected — upgrading kokoro…")
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "kokoro>=0.9",
             "--upgrade", "--quiet", "--disable-pip-version-check"],
            capture_output=True,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace").strip()
            raise RuntimeError(
                f"Kokoro auto-upgrade failed: {stderr[:200]}\n"
                "Run manually: pip install kokoro>=0.9 soundfile"
            ) from first_err

        # Flush any stale kokoro submodules from the import cache
        stale = [k for k in sys.modules if k == "kokoro" or k.startswith("kokoro.")]
        for key in stale:
            del sys.modules[key]

        print("[TTS] Kokoro upgraded — retrying import…")
        try:
            return _try_import()
        except Exception as retry_err:
            raise RuntimeError(
                f"Kokoro still broken after upgrade: {retry_err}\n"
                "Run manually: pip install --upgrade kokoro transformers"
            ) from retry_err


# Kokoro voice prefix → KPipeline lang_code mapping
_KOKORO_LANG_CODES = {
    "a": "a",   # American English  (af_*, am_*)
    "b": "b",   # British English   (bf_*, bm_*)
    "j": "j",   # Japanese          (jf_*, jm_*)
    "z": "z",   # Mandarin Chinese  (zf_*, zm_*)
    "s": "s",   # Spanish           (sf_*, sm_*)
    "f": "f",   # French            (ff_*, fm_*)
    "h": "h",   # Hindi             (hf_*, hm_*)
    "i": "i",   # Italian           (if_*, im_*)
    "p": "p",   # Brazilian Portuguese
    "r": "r",   # Russian           (rf_*, rm_*)
    "e": "e",   # German            (ef_*, em_*)
}


class KokoroTTSEngine:
    """Fully offline Kokoro neural TTS.

    Model (~330 MB) is downloaded from HuggingFace on first use,
    then cached locally — subsequent starts load from disk.

    Warmup strategy: _init() runs synchronously in the background
    _do_tts() thread (not the UI thread).  After the pipeline loads,
    a dummy inference compiles the PyTorch JIT graph immediately so
    the first real speak() call has zero compilation overhead.
    """

    def __init__(self, voice: str = "af_heart", speed: float = 1.0):
        self.voice     = voice
        self.speed     = speed
        self._pipeline = None
        self._lock     = threading.Lock()
        self._init()   # blocking, but called from background thread

    @property
    def _lang_code(self) -> str:
        prefix = self.voice[0].lower() if self.voice else "a"
        return _KOKORO_LANG_CODES.get(prefix, "a")

    def _init(self) -> None:
        if self._pipeline is not None:
            return

        lang = self._lang_code

        # Prefer GPU — Kokoro on CUDA is ~10x faster than CPU.
        try:
            import torch
            if torch.cuda.is_available():
                device = "cuda"
            elif torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"
                
            if device == "cpu":
                import os as _os
                n_threads = max(1, min(4, (_os.cpu_count() or 4) // 2))
                try:
                    torch.set_num_threads(n_threads)
                    torch.set_num_interop_threads(2)
                except RuntimeError:
                    pass
                print(
                    f"[TTS] Kokoro on CPU — for faster speech install CUDA PyTorch:\n"
                    "      pip install torch --index-url https://download.pytorch.org/whl/cu118"
                )
        except Exception:
            device = "cpu"

        print(f"[TTS] Kokoro — loading (lang='{lang}', device='{device}')…")

        KPipeline = _import_kokoro_pipeline()

        def _create_pipeline():
            try:
                return KPipeline(lang_code=lang, device=device)
            except TypeError:
                return KPipeline(lang_code=lang)   # older build — no device param

        try:
            self._pipeline = _create_pipeline()
        except Exception as _first_err:
            # Offline flag set but model not cached yet → clear flags and download once.
            # Keywords cover multiple huggingface_hub error message variants across versions.
            _e = str(_first_err).lower()
            _offline_keywords = (
                "offline", "not found", "cache", "localentry",
                "does not exist", "outgoing", "local_files_only",
            )
            if any(k in _e for k in _offline_keywords):
                print("[TTS] Kokoro model not in local cache — downloading (one-time, internet required)…")
                os.environ.pop("HF_HUB_OFFLINE",      None)
                os.environ.pop("TRANSFORMERS_OFFLINE", None)
                os.environ.pop("HF_DATASETS_OFFLINE",  None)
                try:
                    self._pipeline = _create_pipeline()
                except Exception as _dl_err:
                    raise RuntimeError(
                        f"Kokoro model download failed.\n"
                        f"Internet access is required the first time to download the voice model (~330 MB).\n"
                        f"After the first download it runs fully offline.\n"
                        f"Tip: Switch to EdgeTTS (free, no download) in the Configure panel if offline.\n"
                        f"Details: {_dl_err}"
                    ) from _dl_err
            else:
                raise

        print("[TTS] Kokoro compiling (first-time only)…")
        # Warmup: compiles PyTorch JIT graph so first real speak() call is instant.
        try:
            for _ in self._pipeline("hello", voice=self.voice, speed=self.speed):
                pass
            print("[TTS] Kokoro ready.")
        except Exception as e:
            print(f"[TTS] Kokoro warmup warning: {e}")

    def speak(self, text: str) -> None:
        with self._lock:
            if self._pipeline is None:
                self._init()

        # ── Concurrent synthesise + playback ────────────────────────────────
        # Kokoro generates audio chunks lazily.  Without threading, we:
        #   synthesise chunk N → play N → synthesise N+1 → play N+1 …
        # With a producer/consumer pair, chunk N+1 synthesises WHILE chunk N
        # plays, cutting perceived latency by the playback duration of all but
        # the last chunk (typically 1-3 s on multi-sentence responses).
        audio_q: "_queue.Queue[np.ndarray | None]" = _queue.Queue(maxsize=4)
        synth_error: list[Exception] = []

        def _synth():
            try:
                for _, _, audio in self._pipeline(text, voice=self.voice, speed=self.speed):
                    if audio is not None:
                        arr = _to_numpy(audio)
                        arr = _compress_silence(arr)
                        if arr.size > 0:
                            audio_q.put(arr)          # blocks if player is slow (backpressure)
            except Exception as exc:
                synth_error.append(exc)
            finally:
                audio_q.put(None)                     # sentinel → player exits

        synth_thread = threading.Thread(target=_synth, daemon=True)
        synth_thread.start()

        # Player runs in this thread so sd.wait() doesn't block the synth thread.
        while True:
            arr = audio_q.get()
            if arr is None:
                break
            _play_np(arr, 24000)

        synth_thread.join()

        if synth_error:
            raise synth_error[0]


class ElevenLabsTTSEngine:
    """ElevenLabs cloud TTS – API key required. Supports Hindi + English
    natively via the multilingual model (no language switch needed)."""

    def __init__(self, api_key: str, voice_id: str = "21m00Tcm4TlvDq8ikWAM"):
        # Default voice: "Rachel" — warm, clear, female. (Not Adam/pNInz6ob...,
        # which is ElevenLabs' default male voice and was set here before.)
        self.api_key  = api_key
        self.voice_id = voice_id

    def speak(self, text: str) -> None:
        import requests
        headers = {
            "xi-api-key":   self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text":     text,
            "model_id": "eleven_multilingual_v2",   # handles Hindi + English + code-switching
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }
        resp = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}",
            json=payload, headers=headers, timeout=30,
        )
        resp.raise_for_status()
        _play_audio_bytes(resp.content)


class PiperTTSEngine:
    """
    Piper – free, fully offline TTS. Used as SAM's offline fallback when
    ElevenLabs isn't configured or isn't reachable.

    Voice models are downloaded once from Hugging Face (rhasspy/piper-voices)
    on first use, then cached locally under ~/.local/share/piper-voices —
    after that first download, this engine needs no internet at all.

    Default voice "en_US-amy-medium" is a clear female English voice. Piper
    doesn't have native Hindi+English code-switching like ElevenLabs does —
    for Hindi text, pair with a Hindi Piper voice (e.g. "hi_IN-*") if/when
    one is needed; for now this covers the English side of the offline path.
    """

    def __init__(self, voice: str = "en_US-amy-medium"):
        self.voice = voice
        self._piper_voice = None  # lazy-loaded on first speak() call

    def _ensure_loaded(self):
        if self._piper_voice is not None:
            return
        from piper import PiperVoice
        from piper.download_voices import download_voice
        from pathlib import Path

        cache_dir = Path.home() / ".local" / "share" / "piper-voices"
        cache_dir.mkdir(parents=True, exist_ok=True)
        model_path = cache_dir / f"{self.voice}.onnx"

        if not model_path.exists():
            print(f"[TTS] Piper voice '{self.voice}' not cached — downloading (one-time, internet required)…")
            download_voice(self.voice, cache_dir)
            print(f"[TTS] Piper voice '{self.voice}' ready.")

        self._piper_voice = PiperVoice.load(str(model_path))

    def speak(self, text: str) -> None:
        self._ensure_loaded()
        chunks = self._piper_voice.synthesize(text)
        sample_rate = self._piper_voice.config.sample_rate
        
        for c in chunks:
            samples = c.audio_float_array
            
            # macOS CoreAudio frequently rejects 22050Hz and other non-standard rates,
            # resulting in a PaMacCore err='-50' and blasting static noise through the speakers.
            if __import__("sys").platform == "darwin" and sample_rate not in (44100, 48000):
                import scipy.signal
                samples = scipy.signal.resample_poly(samples, 48000, sample_rate)
                play_rate = 48000
            else:
                play_rate = sample_rate
                
            _play_np(samples, sample_rate=play_rate)


class HybridTTSEngine:
    """
    ElevenLabs first (natural, multilingual), Piper as the offline/no-key
    fallback — matches SAM's hybrid-brain pattern: prefer the best cloud
    option, never let a missing key or a network hiccup leave SAM silent.
    """

    def __init__(self, elevenlabs_api_key: str = "", voice_id: str = "21m00Tcm4TlvDq8ikWAM",
                 piper_voice: str = "en_US-amy-medium"):
        self._eleven = ElevenLabsTTSEngine(elevenlabs_api_key, voice_id) if elevenlabs_api_key else None
        self._piper  = PiperTTSEngine(piper_voice)

    def speak(self, text: str) -> None:
        if self._eleven:
            try:
                self._eleven.speak(text)
                return
            except Exception as e:
                print(f"[TTS] ElevenLabs failed ({e}) — falling back to Piper.")
        self._piper.speak(text)


class NativeSpeechEngine:
    """Offline operating-system speech fallback (including macOS's built-in `say`)."""

    def __init__(self):
        self._process = None
        self._lock = threading.Lock()

    def speak(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        system = platform.system()
        if system == "Darwin":
            command = ["say", "-r", "185", text]
        elif system == "Windows":
            powershell = shutil.which("powershell") or shutil.which("pwsh")
            if not powershell:
                raise RuntimeError("PowerShell speech is unavailable")
            script = (
                "Add-Type -AssemblyName System.Speech; "
                "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                "$s.Speak([Console]::In.ReadToEnd())"
            )
            command = [powershell, "-NoProfile", "-NonInteractive", "-Command", script]
        else:
            speaker = shutil.which("espeak-ng") or shutil.which("espeak") or shutil.which("spd-say")
            if not speaker:
                raise RuntimeError("Install espeak-ng or speech-dispatcher for offline speech")
            command = [speaker, text]
        process = subprocess.Popen(command, stdin=subprocess.PIPE if system == "Windows" else subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
        with self._lock:
            self._process = process
        try:
            process.communicate(input=text if system == "Windows" else None)
            if process.returncode:
                with self._lock:
                    stopped_by_user = self._process is not process
                if not stopped_by_user:
                    raise RuntimeError(f"System speech exited with code {process.returncode}")
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None

    def stop(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
        if process and process.poll() is None:
            process.terminate()


class FallbackTTSEngine:
    """Try the configured voice engine, then use local system speech if it fails."""

    def __init__(self, primary, fallback):
        self.primary = primary
        self.fallback = fallback

    def speak(self, text: str) -> None:
        try:
            self.primary.speak(text)
        except Exception as exc:
            print(f"[TTS] Configured voice unavailable ({exc}); using system speech.")
            self.fallback.speak(text)

    def stop(self) -> None:
        for engine in (self.primary, self.fallback):
            stop = getattr(engine, "stop", None)
            if stop:
                try:
                    stop()
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Thread-safe player wrapper
# ---------------------------------------------------------------------------

class TTSPlayer:
    """
    Wraps any *Engine. Exposes a blocking speak() method
    meant to be called from a dedicated background thread.
    """

    def __init__(self, engine):
        self._engine  = engine
        self._playing = False
        self._lock    = threading.Lock()

    @property
    def is_playing(self) -> bool:
        return self._playing

    def speak(
        self,
        text:     str,
        on_start: Optional[Callable] = None,
        on_done:  Optional[Callable] = None,
    ) -> None:
        """Synthesise and play text. BLOCKING – call from a dedicated thread."""
        try:
            with self._lock:
                self._playing = True
            if on_start:
                on_start()
            self._engine.speak(text)
        except Exception as e:
            print(f"[TTS] Error: {e}")
        finally:
            with self._lock:
                self._playing = False
            if on_done:
                on_done()

    def stop(self) -> None:
        try:
            sd.stop()
        finally:
            stop_engine = getattr(self._engine, "stop", None)
            if stop_engine:
                stop_engine()
        with self._lock:
            self._playing = False


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_tts_player(config: dict) -> TTSPlayer:
    engine_name = str(config.get("tts_engine", "edgetts") or "edgetts").strip().lower()
    
    # Older config files use "gemini"; use native offline speech for that setting.
    if engine_name == "gemini":
        # The old config value should still speak offline without depending on Edge TTS.
        engine_name = "system"

    if engine_name == "system":
        engine = NativeSpeechEngine()
    elif engine_name == "kokoro":
        voice  = config.get("tts_voice", "af_heart")
        speed  = float(config.get("tts_speed", 1.0))
        engine = KokoroTTSEngine(voice=voice, speed=speed)
    elif engine_name == "elevenlabs":
        api_key  = config.get("elevenlabs_api_key", "")
        voice_id = config.get("tts_voice", "21m00Tcm4TlvDq8ikWAM")
        engine   = ElevenLabsTTSEngine(api_key=api_key, voice_id=voice_id)
    elif engine_name == "piper":
        voice  = config.get("piper_voice", "en_US-amy-medium")
        engine = PiperTTSEngine(voice=voice)
    elif engine_name == "hybrid":
        api_key     = config.get("elevenlabs_api_key", "")
        if api_key:
            voice_id    = config.get("tts_voice", "21m00Tcm4TlvDq8ikWAM")
            piper_voice = config.get("piper_voice", "en_US-amy-medium")
            engine      = HybridTTSEngine(elevenlabs_api_key=api_key, voice_id=voice_id, piper_voice=piper_voice)
        else:
            # If hybrid requested but no ElevenLabs key, fallback to EdgeTTS instead of Piper for speed
            voice  = config.get("tts_voice", "en-US-AriaNeural")
            engine = EdgeTTSEngine(voice=voice)
    else:
        # Default to EdgeTTS (free, no API key, fast)
        voice  = config.get("tts_voice", "en-US-AriaNeural")
        engine = EdgeTTSEngine(voice=voice)
        
    return TTSPlayer(FallbackTTSEngine(engine, NativeSpeechEngine()))
