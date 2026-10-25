import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from actions import file_controller as fc


class FileControllerTests(unittest.TestCase):
    def test_safe_path_stays_inside_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            with patch.object(fc, "_SAFE_ROOTS", [root]):
                self.assertTrue(fc._is_safe_path(root / "ok.txt"))
                self.assertFalse(fc._is_safe_path(root.parent / "outside.txt"))

    def test_create_read_and_write(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            with patch.object(fc, "_SAFE_ROOTS", [root]):
                self.assertIn("File created", fc.create_file(str(root), "a.txt", "hello"))
                self.assertEqual(fc.read_file(str(root), "a.txt"), "hello")
                self.assertIn("Written to", fc.write_file(str(root), "a.txt", " world"))
                self.assertEqual(fc.read_file(str(root), "a.txt"), " world")


if __name__ == "__main__":
    unittest.main()
