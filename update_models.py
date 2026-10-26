import os
from pathlib import Path

def replace_in_file(path, old, new):
    content = path.read_text(encoding="utf-8")
    if old in content:
        content = content.replace(old, new)
        path.write_text(content, encoding="utf-8")
        print(f"Updated {path}")

if __name__ == "__main__":
    actions_dir = Path("actions")
    for p in actions_dir.glob("*.py"):
        replace_in_file(p, "gemini-2.5-flash-lite", "gemini-3.8-flash")
        replace_in_file(p, "gemini-2.5-flash-native-audio-preview-12-2025", "gemini-3.8-flash")
        replace_in_file(p, "gemini-2.5-flash", "gemini-3.8-flash")

    core_dir = Path("core")
    for p in core_dir.glob("*.py"):
        replace_in_file(p, "gemini-2.5-flash-lite", "gemini-3.8-flash")
        replace_in_file(p, "gemini-2.5-flash-native-audio-preview-12-2025", "gemini-3.8-flash")
        replace_in_file(p, "gemini-2.5-flash", "gemini-3.8-flash")

    print("Done!")
