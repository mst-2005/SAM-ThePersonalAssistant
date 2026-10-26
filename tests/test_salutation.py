import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.intent_analyzer import analyze_query_fast
from core.llm_client import get_salutation, set_salutation


class SalutationTests(unittest.TestCase):
    def test_get_and_set_salutation(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_file = Path(td) / "api_keys.json"
            cfg_file.write_text("{}", encoding="utf-8")
            with patch("core.llm_client.CONFIG_PATH", cfg_file):
                # Default
                self.assertEqual(get_salutation(), "Sir")

                # Set to Ma'am
                set_salutation("Ma'am")
                self.assertEqual(get_salutation(), "Ma'am")

                # Set to Other with name
                set_salutation("Other", "Dr. Banner")
                self.assertEqual(get_salutation(), "Dr. Banner")

                # Set to Sir
                set_salutation("Sir")
                self.assertEqual(get_salutation(), "Sir")

    def test_fast_intent_salutation_commands(self):
        # Voice or text: "call me ma'am"
        res = analyze_query_fast("call me ma'am")
        self.assertIn('call:set_salutation{"salutation": "Ma\'am"}', res)

        # Voice or text: "call me sir"
        res = analyze_query_fast("call me sir")
        self.assertIn('call:set_salutation{"salutation": "Sir"}', res)

        # Voice or text: "call me Natasha"
        res = analyze_query_fast("call me Natasha")
        self.assertIn('call:set_salutation{"salutation": "Other", "other_name": "Natasha"}', res)

        # Voice or text: "switch to ma'am"
        res = analyze_query_fast("switch to ma'am")
        self.assertIn('call:set_salutation{"salutation": "Ma\'am"}', res)

    def test_dynamic_addressing_in_fast_rules(self):
        # Time output with Ma'am
        res_maam = analyze_query_fast("what time is it", address="Ma'am")
        self.assertIn("Ma'am", res_maam)
        self.assertNotIn("sir", res_maam.lower())

        # Date output with custom name
        res_custom = analyze_query_fast("what is the date", address="Alex")
        self.assertIn("Alex", res_custom)
        self.assertNotIn("sir", res_custom.lower())

        # Emotional support with custom name
        res_care = analyze_query_fast("i am happy", address="Sarah")
        self.assertIn("Sarah", res_care)
        self.assertNotIn("sir", res_care.lower())


if __name__ == "__main__":
    unittest.main()
