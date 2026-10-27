"""
Tests for newly added features:
- Clap to Wake detection
- Local LLM provider configuration (Ollama)
- Persistent Chat History access and querying
"""
import time
import unittest
import numpy as np
from core.wake_word import ClapDetector
from core.llm_client import get_llm_provider, get_llm_settings
from core.intent_analyzer import analyze_query_fast
from memory.chat_history import save_message, load_messages, clear_history, get_recent_summary
from actions.chat_history import chat_history


class ClapDetectorTests(unittest.TestCase):
    def test_double_clap_triggers_wake(self):
        woken = []
        detector = ClapDetector(on_wake=lambda: woken.append(True), energy_threshold=1000.0)

        # Baseline quiet frames (20ms each = 320 samples)
        quiet_frame = np.zeros(320, dtype=np.int16)
        for _ in range(5):
            detector.process_chunk(quiet_frame)
        self.assertEqual(len(woken), 0)

        # First clap spike (high amplitude burst)
        clap_spike = np.full(320, 8000, dtype=np.int16)
        detector.process_chunk(clap_spike)
        self.assertEqual(len(woken), 0)  # Single clap does not wake

        # Wait past refractory period (0.15s)
        time.sleep(0.2)

        # Second clap spike
        detector.process_chunk(clap_spike)
        self.assertEqual(len(woken), 1)  # Double clap wakes SAM!

    def test_single_spike_timeout_no_wake(self):
        woken = []
        detector = ClapDetector(on_wake=lambda: woken.append(True), energy_threshold=1000.0)
        clap_spike = np.full(320, 8000, dtype=np.int16)

        detector.process_chunk(clap_spike)
        self.assertEqual(len(woken), 0)

        # Reset detector
        detector.reset()
        self.assertIsNone(detector._first_clap)


from unittest.mock import patch


class LocalLLMConfigTests(unittest.TestCase):
    @patch("core.llm_client._load_config", return_value={"llm_provider": "ollama", "llm_url": "http://localhost:11434", "llm_model": "deepseek-r1"})
    def test_ollama_provider_configuration(self, mock_cfg):
        provider = get_llm_provider()
        self.assertEqual(provider, "ollama")

        url, model = get_llm_settings()
        self.assertEqual(url, "http://localhost:11434")
        self.assertTrue(model.startswith("deepseek-r1"))


class ChatHistoryTests(unittest.TestCase):
    def setUp(self):
        clear_history()

    def tearDown(self):
        clear_history()

    def test_save_and_load_messages(self):
        m1 = save_message("User", "What is the weather today?")
        m2 = save_message("SAM", "It is 22 degrees and sunny.")

        history = load_messages(limit=10)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["role"], "User")
        self.assertEqual(history[0]["content"], "What is the weather today?")
        self.assertEqual(history[1]["role"], "SAM")
        self.assertEqual(history[1]["content"], "It is 22 degrees and sunny.")

    def test_search_messages(self):
        save_message("User", "Deploy project to AWS")
        save_message("SAM", "Deployment successful.")
        save_message("User", "Play some relaxing music")

        aws_matches = load_messages(search="AWS")
        self.assertEqual(len(aws_matches), 1)
        self.assertIn("AWS", aws_matches[0]["content"])

        music_matches = load_messages(search="music")
        self.assertEqual(len(music_matches), 1)

    def test_recent_summary_and_tool_action(self):
        save_message("User", "Hello SAM")
        save_message("SAM", "Greetings! How may I assist you?")

        summary = get_recent_summary(max_turns=2)
        self.assertIn("Hello SAM", summary)
        self.assertIn("Greetings", summary)

        res = chat_history({"action": "recent", "limit": 2})
        self.assertIn("Hello SAM", res)

    def test_fast_intent_for_previous_chats(self):
        queries = [
            "show previous chats",
            "show chat history",
            "previous chats",
            "view past conversations",
            "what did we talk about earlier",
            "open chat history",
        ]
        for q in queries:
            intent = analyze_query_fast(q)
            self.assertIsNotNone(intent, f"Query '{q}' should trigger fast intent")
            self.assertIn("chat_history", intent)


if __name__ == "__main__":
    unittest.main()
