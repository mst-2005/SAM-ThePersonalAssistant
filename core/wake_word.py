"""
Wake word detection for SAM ("Hey Sam").

IMPORTANT — read this before relying on wake-word behaviour:

OpenWakeWord ships 5 pretrained models: alexa, hey_mycroft, hey_jarvis,
timer, weather. There is NO pretrained "Hey Sam" model — nobody has
trained one. Until you train a real one, this module defaults to the
"hey_jarvis" model as a placeholder — it reacts to something that sounds
like "Hey Jarvis", not "Hey Sam". That's a stand-in to get the plumbing
working end-to-end today, not a finished wake word.

To get a real "Hey Sam" detector:
  1. Go to https://openwakeword.com/train (hosted trainer, no GPU needed
     on your end) and generate a model for the phrase "Hey Sam".
  2. Download the resulting .onnx file.
  3. Point WAKE_MODEL_PATH at it (see config below) — no code changes
     needed, everything else in this module stays the same.

Usage:
    from core.wake_word import WakeWordDetector

    detector = WakeWordDetector(on_wake=lambda: print("Woke up!"))
    # Feed it 80ms (1280-sample) int16 mono 16kHz chunks as they arrive:
    detector.process_chunk(pcm_int16_chunk)
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np

BASE_DIR    = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

# openWakeWord expects 80ms chunks at 16kHz = 1280 samples per call.
CHUNK_SAMPLES = 1280


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


class WakeWordDetector:
    """
    Wraps an openWakeWord model and calls `on_wake()` when the wake phrase
    is detected with confidence above `threshold`.

    Feed it raw int16 mono 16kHz audio via process_chunk() — any chunk size
    works, it buffers internally and runs inference every 1280 samples.
    """

    def __init__(
        self,
        on_wake: Callable[[], None],
        model_path: Optional[str] = None,
        threshold: Optional[float] = None,
        cooldown_seconds: float = 2.0,
    ):
        from openwakeword.model import Model
        import openwakeword

        cfg = _load_config()
        model_path = model_path or cfg.get("wake_word_model_path") or None
        threshold  = threshold if threshold is not None else float(cfg.get("wake_word_threshold", 0.5))

        if model_path and Path(model_path).exists():
            paths = [model_path]
            self.model_name = Path(model_path).stem
        else:
            # Placeholder — see module docstring.
            all_paths = openwakeword.get_pretrained_model_paths()
            paths = [p for p in all_paths if "hey_jarvis" in p]
            self.model_name = "hey_jarvis_v0.1"
            print(
                "[WakeWord] No custom 'Hey Sam' model configured — using the "
                "'hey_jarvis' pretrained model as a placeholder. Train a real "
                "one at https://openwakeword.com/train and set "
                "\"wake_word_model_path\" in config/api_keys.json."
            )

        self._model      = Model(wakeword_model_paths=paths)
        self._threshold  = threshold
        self._on_wake     = on_wake
        self._cooldown    = cooldown_seconds
        self._last_wake   = 0.0
        self._buf         = np.array([], dtype=np.int16)

    def process_chunk(self, pcm_int16: np.ndarray) -> None:
        """Feed raw int16 mono 16kHz audio. Call on_wake() internally if triggered."""
        self._buf = np.concatenate([self._buf, pcm_int16])

        while len(self._buf) >= CHUNK_SAMPLES:
            frame, self._buf = self._buf[:CHUNK_SAMPLES], self._buf[CHUNK_SAMPLES:]
            predictions = self._model.predict(frame)
            score = predictions.get(self.model_name, 0.0)

            if score >= self._threshold:
                now = time.monotonic()
                if now - self._last_wake >= self._cooldown:
                    self._last_wake = now
                    try:
                        self._on_wake()
                    except Exception as e:
                        print(f"[WakeWord] on_wake callback error: {e}")

    def reset(self) -> None:
        """Clear internal audio buffer (call after a long mute/pause)."""
        self._buf = np.array([], dtype=np.int16)


class ClapDetector:
    """
    Alternate wake trigger: two sharp claps within ~1.5s wakes SAM, no wake
    phrase needed. This is a simple amplitude-transient heuristic (energy
    spike + fast decay), not a trained model — it will need threshold
    tuning for your room/mic (default threshold assumes typical laptop mic
    gain). A single loud bang can still false-trigger occasionally; the
    double-clap requirement (like an old "Clapper" switch) cuts that down
    a lot compared to a single-clap trigger.

    Feed it the same int16 mono 16kHz chunks as WakeWordDetector.
    """

    FRAME_SAMPLES = 320       # 20ms @ 16kHz
    CLAP_WINDOW    = 1.5      # seconds between the two claps
    REFRACTORY     = 0.15     # seconds — ignore new claps right after one (avoid double-counting one clap's echo)

    def __init__(
        self,
        on_wake: Callable[[], None],
        energy_threshold: Optional[float] = None,
        cooldown_seconds: float = 2.0,
    ):
        cfg = _load_config()
        self._threshold  = energy_threshold if energy_threshold is not None else float(cfg.get("clap_energy_threshold", 4000.0))
        self._on_wake    = on_wake
        self._cooldown   = cooldown_seconds
        self._last_wake  = 0.0
        self._last_clap  = -999.0        # far in the past — first spike is never in refractory
        self._first_clap: Optional[float] = None  # None = no pending first clap
        self._baseline   = 200.0   # running noise-floor estimate
        self._buf        = np.array([], dtype=np.int16)

    def process_chunk(self, pcm_int16: np.ndarray) -> None:
        self._buf = np.concatenate([self._buf, pcm_int16])

        while len(self._buf) >= self.FRAME_SAMPLES:
            frame, self._buf = self._buf[:self.FRAME_SAMPLES], self._buf[self.FRAME_SAMPLES:]
            rms = float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))

            is_spike = rms > self._baseline + self._threshold
            # Slowly adapt baseline toward quiet-room noise floor (ignore spikes themselves).
            if not is_spike:
                self._baseline = 0.98 * self._baseline + 0.02 * rms

            if not is_spike:
                continue

            now = time.monotonic()
            if now - self._last_clap < self.REFRACTORY:
                continue  # same clap's tail, not a new one
            self._last_clap = now

            if self._first_clap is None or (now - self._first_clap) > self.CLAP_WINDOW:
                self._first_clap = now  # this is clap #1 of a new pair
                continue

            # Second clap within the window → wake.
            self._first_clap = None
            if now - self._last_wake >= self._cooldown:
                self._last_wake = now
                try:
                    self._on_wake()
                except Exception as e:
                    print(f"[Clap] on_wake callback error: {e}")

    def reset(self) -> None:
        self._buf = np.array([], dtype=np.int16)
        self._first_clap = None

