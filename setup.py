import subprocess
import sys
import platform
from pathlib import Path

MIN_PYTHON = (3, 11)
if sys.version_info < MIN_PYTHON:
    raise SystemExit(
        f"SAM requires Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+; "
        f"you are running {sys.version_info.major}.{sys.version_info.minor}."
    )

ROOT = Path(__file__).resolve().parent
config_dir = ROOT / "config"
config_dir.mkdir(exist_ok=True)
example = config_dir / "api_keys.example.json"
config = config_dir / "api_keys.json"
if not config.exists() and example.exists():
    config.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    print("Created config/api_keys.json from the example template. Add your Gemini API key before launch.")

print("Installing requirements...")
subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")], check=True)

print("Installing Playwright browsers...")
subprocess.run([sys.executable, "-m", "playwright", "install"], check=True)

print("Running source validation...")
subprocess.run([sys.executable, str(ROOT / "validate.py")], check=True)

if platform.system() == "Windows":
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        postinstall = Path(sys.executable).parent / "Scripts" / "pywin32_postinstall.py"
        print(
            "\n⚠️  pywin32 did not install correctly — desktop shortcut creation "
            "will fall back to a slower method that may not work on this machine.\n"
            "    Try fixing it manually with:\n"
            f'    "{sys.executable}" -m pip install --force-reinstall pywin32\n'
            f'    "{sys.executable}" "{postinstall}" -install\n'
        )

print("\n✅ Setup complete! Run 'python main.py' to start MARK L.")

