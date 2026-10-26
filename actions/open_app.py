import time
import subprocess
import platform
import shutil
import re
from pathlib import Path

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

_SYSTEM = platform.system()

_APP_ALIASES: dict[str, dict[str, str]] = {

    "chrome":             {"Windows": "chrome",                  "Darwin": "Google Chrome",        "Linux": "google-chrome"},
    "google chrome":      {"Windows": "chrome",                  "Darwin": "Google Chrome",        "Linux": "google-chrome"},
    "firefox":            {"Windows": "firefox",                 "Darwin": "Firefox",              "Linux": "firefox"},
    "edge":               {"Windows": "msedge",                  "Darwin": "Microsoft Edge",       "Linux": "microsoft-edge"},
    "brave":              {"Windows": "brave",                   "Darwin": "Brave Browser",        "Linux": "brave-browser"},
    "safari":             {"Windows": "msedge",                  "Darwin": "Safari",               "Linux": "firefox"},
    "opera":              {"Windows": "opera",                   "Darwin": "Opera",                "Linux": "opera"},
    "whatsapp":           {"Windows": "WhatsApp",                "Darwin": "WhatsApp",             "Linux": "whatsapp"},
    "telegram":           {"Windows": "Telegram",                "Darwin": "Telegram",             "Linux": "telegram"},
    "discord":            {"Windows": "Discord",                 "Darwin": "Discord",              "Linux": "discord"},
    "slack":              {"Windows": "Slack",                   "Darwin": "Slack",                "Linux": "slack"},
    "zoom":               {"Windows": "Zoom",                    "Darwin": "zoom.us",              "Linux": "zoom"},
    "teams":              {"Windows": "msteams",                 "Darwin": "Microsoft Teams",      "Linux": "teams"},
    "skype":              {"Windows": "skype",                   "Darwin": "Skype",                "Linux": "skype"},
    "signal":             {"Windows": "signal",                  "Darwin": "Signal",               "Linux": "signal"},
    "spotify":            {"Windows": "Spotify",                 "Darwin": "Spotify",              "Linux": "spotify"},
    "vlc":                {"Windows": "vlc",                     "Darwin": "VLC",                  "Linux": "vlc"},
    "netflix":            {"Windows": "Netflix",                 "Darwin": "Netflix",              "Linux": "firefox"},
    "vscode":             {"Windows": "code",                    "Darwin": "Visual Studio Code",   "Linux": "code"},
    "visual studio code": {"Windows": "code",                    "Darwin": "Visual Studio Code",   "Linux": "code"},
    "code":               {"Windows": "code",                    "Darwin": "Visual Studio Code",   "Linux": "code"},
    "terminal":           {"Windows": "wt",                      "Darwin": "Terminal",             "Linux": "x-terminal-emulator"},
    "cmd":                {"Windows": "cmd.exe",                 "Darwin": "Terminal",             "Linux": "bash"},
    "powershell":         {"Windows": "powershell.exe",          "Darwin": "Terminal",             "Linux": "bash"},
    "postman":            {"Windows": "Postman",                 "Darwin": "Postman",              "Linux": "postman"},
    "git":                {"Windows": "git-bash",                "Darwin": "Terminal",             "Linux": "bash"},
    "figma":              {"Windows": "Figma",                   "Darwin": "Figma",                "Linux": "figma"},
    "blender":            {"Windows": "blender",                 "Darwin": "Blender",              "Linux": "blender"},
    "word":               {"Windows": "winword",                 "Darwin": "Microsoft Word",       "Linux": "libreoffice --writer"},
    "excel":              {"Windows": "excel",                   "Darwin": "Microsoft Excel",      "Linux": "libreoffice --calc"},
    "powerpoint":         {"Windows": "powerpnt",                "Darwin": "Microsoft PowerPoint", "Linux": "libreoffice --impress"},
    "libreoffice":        {"Windows": "soffice",                 "Darwin": "LibreOffice",          "Linux": "libreoffice"},
    "notepad":            {"Windows": "notepad.exe",             "Darwin": "TextEdit",             "Linux": "gedit"},
    "textedit":           {"Windows": "notepad.exe",             "Darwin": "TextEdit",             "Linux": "gedit"},
    "explorer":           {"Windows": "explorer.exe",            "Darwin": "Finder",               "Linux": "nautilus"},
    "file explorer":      {"Windows": "explorer.exe",            "Darwin": "Finder",               "Linux": "nautilus"},
    "finder":             {"Windows": "explorer.exe",            "Darwin": "Finder",               "Linux": "nautilus"},
    "task manager":       {"Windows": "taskmgr.exe",             "Darwin": "Activity Monitor",     "Linux": "gnome-system-monitor"},
    "settings":           {"Windows": "ms-settings:",            "Darwin": "System Preferences",   "Linux": "gnome-control-center"},
    "calculator":         {"Windows": "calc.exe",                "Darwin": "Calculator",           "Linux": "gnome-calculator"},
    "paint":              {"Windows": "mspaint.exe",             "Darwin": "Preview",              "Linux": "gimp"},
    "instagram":          {"Windows": "Instagram",               "Darwin": "Instagram",            "Linux": "firefox"},
    "tiktok":             {"Windows": "TikTok",                  "Darwin": "TikTok",               "Linux": "firefox"},
    "notion":             {"Windows": "Notion",                  "Darwin": "Notion",               "Linux": "notion"},
    "moodle":             {"Windows": "Moodle",                  "Darwin": "Moodle",               "Linux": "moodle"},
    "m o o d l e":        {"Windows": "Moodle",                  "Darwin": "Moodle",               "Linux": "moodle"},
    "model":              {"Windows": "Moodle",                  "Darwin": "Moodle",               "Linux": "moodle"},
    "open model":         {"Windows": "Moodle",                  "Darwin": "Moodle",               "Linux": "moodle"},
    "modelling":          {"Windows": "Moodle",                  "Darwin": "Moodle",               "Linux": "moodle"},
    "notebooklm":         {"Windows": "https://notebooklm.google.com", "Darwin": "https://notebooklm.google.com", "Linux": "https://notebooklm.google.com"},
    "notebook lm":        {"Windows": "https://notebooklm.google.com", "Darwin": "https://notebooklm.google.com", "Linux": "https://notebooklm.google.com"},
    "notebook m":         {"Windows": "https://notebooklm.google.com", "Darwin": "https://notebooklm.google.com", "Linux": "https://notebooklm.google.com"},
    "youtube":            {"Windows": "https://www.youtube.com", "Darwin": "https://www.youtube.com", "Linux": "https://www.youtube.com"},
    "chatgpt":            {"Windows": "https://chatgpt.com",     "Darwin": "ChatGPT",              "Linux": "https://chatgpt.com"},
    "obsidian":           {"Windows": "Obsidian",                "Darwin": "Obsidian",             "Linux": "obsidian"},
    "capcut":             {"Windows": "CapCut",                  "Darwin": "CapCut",               "Linux": "capcut"},
    "steam":              {"Windows": "steam",                   "Darwin": "Steam",                "Linux": "steam"},
    "epic":               {"Windows": "EpicGamesLauncher",       "Darwin": "Epic Games Launcher",  "Linux": "legendary"},
    "epic games":         {"Windows": "EpicGamesLauncher",       "Darwin": "Epic Games Launcher",  "Linux": "legendary"},
    "antigravity":        {"Windows": "Antigravity IDE",         "Darwin": "Antigravity IDE",      "Linux": "antigravity"},
    "antigravity ide":    {"Windows": "Antigravity IDE",         "Darwin": "Antigravity IDE",      "Linux": "antigravity"},
    "cursor":             {"Windows": "Cursor",                  "Darwin": "Cursor",               "Linux": "cursor"},
    "claude":             {"Windows": "Claude",                  "Darwin": "Claude",               "Linux": "claude"},
    "docker":             {"Windows": "Docker Desktop",          "Darwin": "Docker",               "Linux": "docker"},
    "ollama":             {"Windows": "ollama",                  "Darwin": "Ollama",               "Linux": "ollama"},
    "xcode":              {"Windows": "code",                    "Darwin": "Xcode",                "Linux": "code"},
    "apple music":        {"Windows": "https://music.apple.com", "Darwin": "Music",                "Linux": "https://music.apple.com"},
    "music":              {"Windows": "https://music.apple.com", "Darwin": "Music",                "Linux": "https://music.apple.com"},
    "notes":              {"Windows": "notepad.exe",             "Darwin": "Notes",                "Linux": "gedit"},
    "reminders":          {"Windows": "ms-to-do:",               "Darwin": "Reminders",            "Linux": "gnome-todo"},
    "calendar":           {"Windows": "outlookcal:",             "Darwin": "Calendar",             "Linux": "gnome-calendar"},
    "system settings":    {"Windows": "ms-settings:",            "Darwin": "System Settings",      "Linux": "gnome-control-center"},
    "github desktop":     {"Windows": "GitHubDesktop",           "Darwin": "GitHub Desktop",       "Linux": "github-desktop"},
}


def _normalize(raw: str) -> str:
    key = raw.lower().strip()

    if key in _APP_ALIASES:
        return _APP_ALIASES[key].get(_SYSTEM, raw)

    for alias_key, os_map in _APP_ALIASES.items():
        if alias_key in key or key in alias_key:
            return os_map.get(_SYSTEM, raw)

    return raw  

def _launch_windows(app_name: str) -> bool:

    if shutil.which(app_name) or shutil.which(app_name.split(".")[0]):
        try:
            subprocess.Popen(
                app_name,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(1.5)
            return True
        except Exception as e:
            print(f"[open_app] subprocess failed: {e}")

    if ":" in app_name:
        try:
            subprocess.Popen(f"start {app_name}", shell=True)
            time.sleep(1.0)
            return True
        except Exception:
            pass

    try:
        import pyautogui
        pyautogui.PAUSE = 0.1
        pyautogui.press("win")
        time.sleep(0.7)
        pyautogui.write(app_name, interval=0.05)
        time.sleep(0.9)
        pyautogui.press("enter")
        time.sleep(2.5)
        return True
    except Exception as e:
        print(f"[open_app] Start Menu search failed: {e}")

    return False


def _find_installed_mac_app(target: str) -> str | None:
    import os
    import difflib
    search_dirs = ["/Applications", "/System/Applications", os.path.expanduser("~/Applications")]
    app_names = []
    for d in search_dirs:
        if os.path.isdir(d):
            try:
                for entry in os.listdir(d):
                    if entry.endswith(".app"):
                        app_names.append(entry[:-4])
            except Exception:
                pass
    if not app_names:
        return None

    target_clean = target.lower().strip()
    target_clean = re.sub(r"\b(?:the\s+app|the\s+application|app|application)\b", "", target_clean).strip()
    target_compressed = target_clean.replace(" ", "").replace("-", "").replace(".", "")

    # 1. Exact match (case insensitive)
    for a in app_names:
        if a.lower() == target_clean:
            return a

    # 2. Compressed match
    for a in app_names:
        a_compressed = a.lower().replace(" ", "").replace("-", "").replace(".", "")
        if a_compressed == target_compressed:
            return a

    # 3. Substring match
    for a in app_names:
        if target_clean and (target_clean in a.lower() or a.lower() in target_clean):
            return a

    # 4. Fuzzy match with close threshold
    comp_map = {a.lower().replace(" ", "").replace("-", "").replace(".", ""): a for a in app_names}
    fuzzy_matches = difflib.get_close_matches(target_compressed, list(comp_map.keys()), n=1, cutoff=0.55)
    if fuzzy_matches:
        return comp_map[fuzzy_matches[0]]

    return None

def _launch_macos(app_name: str) -> bool:
    # First resolve against actual installed apps on disk
    resolved = _find_installed_mac_app(app_name)
    targets_to_try = [resolved, app_name] if resolved else [app_name]

    for target in targets_to_try:
        if not target:
            continue
        try:
            result = subprocess.run(
                ["open", "-a", target],
                capture_output=True, timeout=8
            )
            if result.returncode == 0:
                time.sleep(0.5)
                return True
        except Exception:
            pass

        try:
            result = subprocess.run(
                ["open", "-a", f"{target}.app"],
                capture_output=True, timeout=8
            )
            if result.returncode == 0:
                time.sleep(0.5)
                return True
        except Exception:
            pass

    binary = shutil.which(app_name) or shutil.which(app_name.lower())
    if binary:
        try:
            subprocess.Popen(
                [binary],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(0.5)
            return True
        except Exception:
            pass

    return False


_LINUX_TERMINAL_FALLBACKS = [
    "x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal",
    "xterm", "lxterminal", "mate-terminal", "tilix", "alacritty", "kitty",
]

def _launch_linux(app_name: str) -> bool:

    # terminal emulators: try common ones in order
    if app_name in ("x-terminal-emulator", "gnome-terminal", "terminal"):
        for term in _LINUX_TERMINAL_FALLBACKS:
            if shutil.which(term):
                try:
                    subprocess.Popen([term], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    time.sleep(1.0)
                    return True
                except Exception:
                    continue

    binary = (
        shutil.which(app_name) or
        shutil.which(app_name.lower()) or
        shutil.which(app_name.lower().replace(" ", "-")) or
        shutil.which(app_name.lower().replace(" ", "_"))
    )
    if binary:
        try:
            subprocess.Popen(
                [binary],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(1.0)
            return True
        except Exception:
            pass

    try:
        subprocess.run(
            ["xdg-open", app_name],
            capture_output=True, timeout=5
        )
        return True
    except Exception:
        pass

    for desktop_name in [
        app_name.lower(),
        app_name.lower().replace(" ", "-"),
        app_name.lower().replace(" ", ""),
    ]:
        try:
            result = subprocess.run(
                ["gtk-launch", desktop_name],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                return True
        except Exception:
            pass

    return False


_OS_LAUNCHERS = {
    "Windows": _launch_windows,
    "Darwin":  _launch_macos,
    "Linux":   _launch_linux,
}

def play_spotify(song: str, browser: str = "") -> str:
    """Plays or searches a song on Spotify (desktop app if installed, or Spotify Web fallback)."""
    import urllib.parse
    from core.llm_client import get_salutation
    addr = get_salutation()
    song_clean = (song or "").strip()
    if not song_clean:
        return f"Please specify a song to play on Spotify, {addr}."
    encoded = urllib.parse.quote_plus(song_clean)

    # Check if native desktop app exists
    is_installed = False
    if _SYSTEM == "Darwin":
        is_installed = bool(_find_installed_mac_app("Spotify"))
    elif _SYSTEM == "Windows":
        is_installed = bool(shutil.which("spotify") or (Path.home() / "AppData/Roaming/Spotify/Spotify.exe").exists())
    else:
        is_installed = bool(shutil.which("spotify"))

    if is_installed:
        try:
            if _SYSTEM == "Darwin":
                subprocess.Popen(["open", f"spotify:search:{encoded}"])
            elif _SYSTEM == "Windows":
                subprocess.Popen(["cmd", "/c", "start", f"spotify:search:{encoded}"], shell=False)
            else:
                subprocess.Popen(["spotify", f"spotify:search:{encoded}"])
            return f"I am opening Spotify right now to play {song_clean} for you, {addr}."
        except Exception as e:
            print(f"[open_app] Native Spotify launch error: {e}")

    # Fallback to Spotify Web Player
    web_url = f"https://open.spotify.com/search/{encoded}"
    try:
        if _SYSTEM == "Darwin":
            if browser and browser.lower() in ("chrome", "google chrome"):
                subprocess.Popen(["open", "-a", "Google Chrome", web_url])
            else:
                subprocess.Popen(["open", web_url])
        elif _SYSTEM == "Windows":
            if browser and browser.lower() in ("chrome", "google chrome"):
                subprocess.Popen(["cmd", "/c", "start", "chrome", web_url], shell=False)
            else:
                subprocess.Popen(["cmd", "/c", "start", "", web_url], shell=False)
        else:
            subprocess.Popen(["xdg-open", web_url])
        return f"I am opening Spotify Web right now to play {song_clean} for you, {addr}."
    except Exception as e:
        return f"Failed to launch Spotify player: {e}"


def open_app(
    parameters=None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters if isinstance(parameters, dict) else {}
    action = params.get("action", "").lower().strip()

    # Route music playback
    if action in ("play_spotify", "spotify"):
        song = params.get("song") or params.get("query") or params.get("name") or params.get("app_name") or ""
        browser = params.get("browser", "")
        return play_spotify(song, browser=browser)

    if action in ("play_music", "music"):
        target = (params.get("target") or "spotify").lower().strip()
        song = params.get("song") or params.get("query") or params.get("name") or ""
        browser = params.get("browser", "")
        if "youtube" in target or "chrome" in target:
            from actions.youtube_video import youtube_video
            return youtube_video({"action": "play", "query": song, "browser": browser})
        return play_spotify(song, browser=browser)

    app_name = params.get("app_name") or params.get("name") or params.get("query") or ""
    app_name = str(app_name).strip()

    if not app_name:
        return "No application name provided."

    launcher = _OS_LAUNCHERS.get(_SYSTEM)
    if launcher is None:
        return f"Unsupported operating system: {_SYSTEM}"

    normalized = _normalize(app_name)
    print(f"[open_app] Launching: '{app_name}' → '{normalized}' ({_SYSTEM})")

    if player:
        player.write_log(f"[open_app] {app_name}")

    # Check if target is a web URL (e.g. NotebookLM, YouTube)
    if normalized.startswith("http://") or normalized.startswith("https://"):
        try:
            import webbrowser
            webbrowser.open(normalized)
            return f"Opened {app_name}."
        except Exception as e:
            if _SYSTEM == "Darwin":
                subprocess.run(["open", normalized])
                return f"Opened {app_name}."
            return f"Failed to open web app: {e}"

    try:
        if launcher(normalized):
            return f"Opened {app_name}."
        if normalized.lower() != app_name.lower():
            if launcher(app_name):
                return f"Opened {app_name}."
        return (
            f"Could not confirm that {app_name} launched. "
            f"It may still be loading, or it might not be installed."
        )
    except Exception as e:
        print(f"[open_app] Error: {e}")
        return f"Failed to open {app_name}: {e}"