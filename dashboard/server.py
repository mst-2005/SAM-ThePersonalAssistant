"""
dashboard/server.py — SAM Local HTTP Dashboard

Plain HTTP on port 8000 (no SSL warnings, no firewall issues).
Security at the application layer: AES-256-CBC with session-key-derived key.
CryptoJS is auto-downloaded once and served locally — no CDN needed after that.

Install deps:  pip install fastapi "uvicorn[standard]" cryptography
"""

import asyncio
import base64
import hashlib
import json
import re
import sys
import subprocess
import shutil
import secrets
import socket
import string
import time
from pathlib import Path

_DEPS_OK = False
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
    from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
    import uvicorn
    _DEPS_OK = True
except ImportError:
    pass

# python-multipart is required for file uploads — optional dependency
_UPLOAD_OK = False
try:
    from fastapi import UploadFile, File as FastAPIFile, Form as FastAPIForm
    _UPLOAD_OK = True
except Exception:
    pass

BASE_DIR    = Path(__file__).resolve().parent.parent
STATIC_DIR  = Path(__file__).parent / "static"
PORT        = 8000
MAX_UPLOAD_MB = 500


def _make_uploads_dir() -> Path:
    """Return (and create) the cross-platform uploads folder."""
    for candidate in [
        Path.home() / "Downloads" / "SAM Uploads",
        Path.home() / "Documents" / "SAM Uploads",
        BASE_DIR / "uploads",
    ]:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except Exception:
            pass
    return BASE_DIR / "uploads"


UPLOADS_DIR = _make_uploads_dir()

def _get_gemini_key() -> str | None:
    try:
        import json as _json
        with open(BASE_DIR / "config" / "api_keys.json", "r", encoding="utf-8") as f:
            return _json.load(f).get("gemini_api_key")
    except Exception:
        return None

_KEY_CHARS = [c for c in (string.ascii_uppercase + string.digits)
              if c not in ('O', 'I', 'L', '0', '1')]

# ── AES-256-CBC ───────────────────────────────────────────────────────────────
_AES_SALT = b'SAM-DASHBOARD-v1'


def _derive_key(session_key: str) -> bytes:
    """SHA-256(sessionKey‖salt) → 32-byte AES-256 key (microseconds, no PBKDF2 needed)."""
    return hashlib.sha256(session_key.encode('utf-8') + _AES_SALT).digest()


def _decrypt_cbc(aes_key: bytes, enc_b64: str) -> str:
    """Decrypt base64(IV[16] ‖ ciphertext) with AES-256-CBC + PKCS7."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as sym_pad
    raw      = base64.b64decode(enc_b64)
    iv, ct   = raw[:16], raw[16:]
    dec      = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).decryptor()
    padded   = dec.update(ct) + dec.finalize()
    unpadder = sym_pad.PKCS7(128).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode('utf-8')


# ── CryptoJS (auto-download once, served locally) ─────────────────────────────
_CRYPTOJS_CDN  = ("https://cdnjs.cloudflare.com/ajax/libs/"
                  "crypto-js/4.2.0/crypto-js.min.js")
_CRYPTOJS_FILE = STATIC_DIR / "crypto-js.min.js"


def _ensure_network_access(port: int) -> None:
    """Cross-platform, best-effort: open port in the OS firewall for LAN access.

    Runs in a background thread — never blocks uvicorn startup.

    Windows : writes a .bat file, runs it elevated via Windows ShellExecuteW
              (native UAC dialog, guaranteed to appear). One-time setup.
    macOS   : osascript admin dialog if the Application Firewall is on.
    Linux   : pkexec GUI → sudo -n → prints manual command as fallback.
    """
    import sys, subprocess, os, tempfile, threading

    # ── Windows ──────────────────────────────────────────────────────────────
    if sys.platform == "win32":
        import ctypes, time

        port_rule = f"SAM Dashboard Port {port}"
        prog_rule  = "SAM Dashboard Python"
        py_exe     = sys.executable

        def _netsh_rule_exists(name: str) -> bool:
            try:
                r = subprocess.run(
                    ["netsh", "advfirewall", "firewall", "show", "rule", f"name={name}"],
                    capture_output=True, text=True, timeout=5,
                )
                return r.returncode == 0 and "No rules match" not in r.stdout
            except Exception:
                return False

        def _network_is_public() -> bool:
            try:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                     "(Get-NetConnectionProfile | "
                     "Where-Object {$_.NetworkCategory -eq 'Public'} | "
                     "Measure-Object).Count"],
                    capture_output=True, text=True, timeout=6,
                )
                return r.stdout.strip() not in ("", "0")
            except Exception:
                return False

        need_port    = not _netsh_rule_exists(port_rule)
        need_prog    = not _netsh_rule_exists(prog_rule)
        need_private = _network_is_public()

        if not need_port and not need_prog and not need_private:
            return  # already fully configured

        # Build a .bat file — netsh + powershell, runs fast when elevated
        bat_lines = ["@echo off"]
        if need_private:
            bat_lines.append(
                'powershell -NoProfile -NonInteractive -Command "'
                'Get-NetConnectionProfile | '
                "Where-Object {$_.NetworkCategory -eq 'Public'} | "
                'Set-NetConnectionProfile -NetworkCategory Private"'
            )
        if need_port:
            bat_lines.append(
                f'netsh advfirewall firewall add rule '
                f'name="{port_rule}" protocol=TCP dir=in '
                f'localport={port} action=allow'
            )
        if need_prog:
            bat_lines.append(
                f'netsh advfirewall firewall add rule '
                f'name="{prog_rule}" dir=in action=allow '
                f'program="{py_exe}" enable=yes'
            )

        bat_body = "\r\n".join(bat_lines) + "\r\n"
        fd, bat_path = tempfile.mkstemp(suffix=".bat", prefix="sam_fw_")
        try:
            os.write(fd, bat_body.encode("mbcs"))   # Windows cmd.exe expects ANSI
            os.close(fd)
        except Exception:
            try:
                os.close(fd)
            except Exception:
                pass
            return

        # ── Try running directly (succeeds when already admin) ────────────────
        try:
            r = subprocess.run(
                [bat_path], capture_output=True, timeout=8, shell=True
            )
            if r.returncode == 0:
                print(f"[Dashboard] Firewall configured for port {port}.")
                try:
                    os.unlink(bat_path)
                except Exception:
                    pass
                return
        except Exception:
            pass

        try:
            os.unlink(bat_path)
        except Exception:
            pass
        finally:
            # Cleanup after the bat has had time to run
            def _cleanup(path: str) -> None:
                time.sleep(5)
                try:
                    os.unlink(path)
                except Exception:
                    pass
            threading.Thread(target=_cleanup, args=(bat_path,), daemon=True).start()
        return

    # ── macOS ─────────────────────────────────────────────────────────────────
    if sys.platform == "darwin":
        fw_ctl = "/usr/libexec/ApplicationFirewall/socketfilterfw"
        try:
            r = subprocess.run(
                [fw_ctl, "--getglobalstate"], capture_output=True, text=True, timeout=5,
            )
            if "disabled" in r.stdout.lower():
                return  # firewall off — nothing to do

            py = sys.executable
            listed = subprocess.run(
                [fw_ctl, "--listapps"], capture_output=True, text=True, timeout=5,
            )
            if py in listed.stdout:
                return  # already allowed

            print("[Dashboard] One-time network setup — enter your password in the macOS dialog.")
            subprocess.run(
                ["osascript", "-e",
                 f'do shell script "{fw_ctl} --add {py} && {fw_ctl} --unblockapp {py}"'
                 f' with administrator privileges'],
                timeout=60,
            )
        except Exception:
            pass  # macOS firewall is off by default — silent failure is fine
        return

    # ── Linux ─────────────────────────────────────────────────────────────────
    def _privileged(cmd: list[str]) -> bool:
        for prefix in (["pkexec"], ["sudo", "-n"]):
            try:
                r = subprocess.run(prefix + cmd, capture_output=True, timeout=30)
                if r.returncode == 0:
                    return True
            except Exception:
                pass
        return False

    try:  # ufw
        r = subprocess.run(["ufw", "status"], capture_output=True, text=True, timeout=5)
        if "active" in r.stdout.lower():
            if _privileged(["ufw", "allow", f"{port}/tcp"]):
                print(f"[Dashboard] ufw: port {port} allowed.")
            else:
                print(f"[Dashboard] Run manually:  sudo ufw allow {port}/tcp")
            return
    except FileNotFoundError:
        pass

    try:  # firewalld
        r = subprocess.run(
            ["firewall-cmd", "--state"], capture_output=True, text=True, timeout=5,
        )
        if "running" in r.stdout.lower():
            ok = (_privileged(["firewall-cmd", "--add-port", f"{port}/tcp", "--permanent"])
                  and _privileged(["firewall-cmd", "--reload"]))
            if ok:
                print(f"[Dashboard] firewalld: port {port} allowed.")
            else:
                print(f"[Dashboard] Run manually:  sudo firewall-cmd --add-port={port}/tcp --permanent && sudo firewall-cmd --reload")
            return
    except FileNotFoundError:
        pass

    try:  # iptables (not persistent but works until reboot)
        r = subprocess.run(["iptables", "-L", "INPUT", "-n"], capture_output=True, timeout=5)
        if r.returncode == 0:
            if _privileged(["iptables", "-A", "INPUT", "-p", "tcp", "--dport", str(port), "-j", "ACCEPT"]):
                print(f"[Dashboard] iptables: port {port} opened.")
            else:
                print(f"[Dashboard] Run manually:  sudo iptables -A INPUT -p tcp --dport {port} -j ACCEPT")
    except FileNotFoundError:
        pass  # no iptables means firewall is probably off — nothing to do


def _ensure_crypto_js() -> None:
    if _CRYPTOJS_FILE.exists():
        return
    try:
        import urllib.request
        print("[Dashboard] Downloading CryptoJS (one-time setup)…")
        urllib.request.urlretrieve(_CRYPTOJS_CDN, str(_CRYPTOJS_FILE))
        print("[Dashboard] CryptoJS cached — will serve locally from now on.")
    except Exception as e:
        print(f"[Dashboard] CryptoJS download failed: {e}")
        print(f"[Dashboard] Encryption will fall back to CDN load on client.")


_ensure_crypto_js()


# ── helpers ───────────────────────────────────────────────────────────────────

def _local_ip() -> str:
    """Return the best LAN-facing IPv4 address, no internet required."""
    # Method 1: route trick (fast, works when internet is available)
    for probe in ("8.8.8.8", "1.1.1.1", "192.168.1.1"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect((probe, 80))
            ip = s.getsockname()[0]
            s.close()
            if not ip.startswith("127."):
                return ip
        except Exception:
            pass

    # Method 2: hostname resolution (works offline on most systems)
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if not ip.startswith("127."):
            return ip
    except Exception:
        pass

    # Method 3: enumerate all interfaces (fully offline, no external deps)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                return ip
    except Exception:
        pass

    return "127.0.0.1"


def _read(name: str) -> str:
    return (STATIC_DIR / name).read_text(encoding="utf-8")


# ── DashboardServer ───────────────────────────────────────────────────────────

class DashboardServer:

    def __init__(self):
        self._ip                          = _local_ip()
        self._tokens: set[str]            = set()
        self._token_keys: dict[str, str]  = {}   # auth_token → session_key
        self._aes_cache:  dict[str, bytes]= {}   # session_key → AES bytes
        self._clients: set[WebSocket]     = set()
        self._history: list[dict]         = []
        self._command_queue               = asyncio.Queue()
        self._wake_callback               = None
        self._connect_callback            = None
        self._pending_keys: dict[str, float] = {}
        self._device_sessions: dict[str, dict] = {}  # device_token → {session_key}
        self._phone_audio_queue: asyncio.Queue    = asyncio.Queue(maxsize=200)
        self._uploads_dir                 = UPLOADS_DIR
        self._user_data_path              = BASE_DIR / "memory" / "dashboard_user_data.json"
        self._user_data_lock              = __import__("threading").RLock()
        self._user_data                   = self._load_user_data()
        self._bionic_started              = False
        self._login_html                  = _read("login.html")
        self._app_html                    = _read("app.html")
        self.app                          = self._build_app()

    def _load_user_data(self) -> dict:
        defaults = {"preferences": {"salutation": "Sir", "other_name": "", "auto_open_bionic": True}, "history": []}
        try:
            if self._user_data_path.exists():
                saved = json.loads(self._user_data_path.read_text(encoding="utf-8"))
                defaults.update(saved if isinstance(saved, dict) else {})
        except Exception as exc:
            print(f"[Dashboard] Could not read user history: {exc}")
        defaults.setdefault("preferences", {"salutation": "Sir", "other_name": "", "auto_open_bionic": True})
        defaults.setdefault("history", [])
        return defaults

    def _save_user_data(self) -> None:
        try:
            self._user_data_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._user_data_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._user_data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._user_data_path)
        except Exception as exc:
            print(f"[Dashboard] Could not save user history: {exc}")

    def _record(self, entry: dict) -> None:
        with self._user_data_lock:
            self._user_data["history"].append({"time": time.time(), **entry})
            self._user_data["history"] = self._user_data["history"][-2000:]
            self._save_user_data()

    def _recent_file_context(self, limit: int = 4, max_chars: int = 6000) -> str:
        """Read bounded text from recent uploads so the selected model can use them."""
        text_suffixes = {".txt", ".md", ".csv", ".tsv", ".json", ".yaml", ".yml",
                         ".xml", ".html", ".htm", ".log", ".py", ".js", ".ts",
                         ".tsx", ".jsx", ".css", ".sql", ".sh", ".rtf"}
        sections = []
        remaining = max_chars
        with self._user_data_lock:
            uploads = [e for e in self._user_data.get("history", []) if e.get("kind") == "file"][-limit:]
        for entry in reversed(uploads):
            relative = str(entry.get("path", ""))
            path = self._uploads_dir / relative
            try:
                resolved = path.resolve()
                if not resolved.is_relative_to(self._uploads_dir.resolve()) or not resolved.is_file():
                    continue
                if resolved.suffix.lower() in text_suffixes:
                    content = resolved.read_text(encoding="utf-8", errors="replace")[:min(5000, remaining)]
                elif resolved.suffix.lower() == ".pdf":
                    try:
                        from pypdf import PdfReader
                        content = "\n".join(page.extract_text() or "" for page in PdfReader(str(resolved)).pages[:12])
                    except Exception:
                        continue
                    content = content[:min(5000, remaining)]
                elif resolved.suffix.lower() == ".docx":
                    try:
                        from docx import Document
                        content = "\n".join(p.text for p in Document(str(resolved)).paragraphs)
                    except Exception:
                        continue
                    content = content[:min(5000, remaining)]
                else:
                    continue
                if content.strip():
                    section = f"Uploaded file: {relative}\n{content}"
                    sections.append(section)
                    remaining -= len(section)
                    if remaining <= 0:
                        break
            except (OSError, ValueError):
                continue
        return "\n\n".join(reversed(sections))

    def _launch_bionic(self) -> None:
        if self._bionic_started or not self._user_data.get("preferences", {}).get("auto_open_bionic", True):
            return
        self._bionic_started = True
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-a", "Bionic"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif sys.platform == "win32":
                subprocess.Popen(["cmd", "/c", "start", "", "Bionic"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                executable = shutil.which("bionic")
                if executable:
                    subprocess.Popen([executable], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("[Dashboard] Requested Bionic startup (if installed).")
        except Exception as exc:
            print(f"[Dashboard] Bionic did not start automatically: {exc}")

    # ── one-time key management ───────────────────────────────────────────

    def new_key(self, expiry_secs: int = 600) -> str:
        now = time.time()
        self._pending_keys = {k: v for k, v in self._pending_keys.items() if v > now}
        key = ''.join(secrets.choice(_KEY_CHARS) for _ in range(6))
        self._pending_keys[key] = now + expiry_secs
        return key

    @staticmethod
    def _ssl_enabled() -> bool:
        certs = BASE_DIR / "config" / "certs"
        return (certs / "sam.key").exists() and (certs / "sam.crt").exists()

    @staticmethod
    def _ensure_ssl_certs() -> bool:
        """Create a local self-signed dashboard certificate on first use.

        The certificate/private key are generated on the user's machine and
        are deliberately not shipped in the source archive. This keeps the
        release free of reusable private key material while preserving the
        optional HTTPS dashboard used by phone pairing.
        """
        import datetime as _dt
        import ipaddress
        import socket
        try:
            from cryptography import x509
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.x509.oid import NameOID

            cert_dir = BASE_DIR / "config" / "certs"
            cert_dir.mkdir(parents=True, exist_ok=True)
            key_path, cert_path = cert_dir / "sam.key", cert_dir / "sam.crt"
            if key_path.exists() and cert_path.exists():
                return True

            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            hostname = socket.gethostname() or "SAM"
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "SAM Dashboard")])
            san = [x509.DNSName("localhost"), x509.DNSName(hostname)]
            try:
                san.append(x509.IPAddress(ipaddress.ip_address(socket.gethostbyname(hostname))))
            except Exception:
                pass
            cert = (x509.CertificateBuilder()
                    .subject_name(name).issuer_name(name)
                    .public_key(key.public_key())
                    .serial_number(x509.random_serial_number())
                    .not_valid_before(_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=1))
                    .not_valid_after(_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=825))
                    .add_extension(x509.SubjectAlternativeName(san), critical=False)
                    .sign(key, hashes.SHA256()))

            key_path.write_bytes(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ))
            cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            try:
                key_path.chmod(0o600)
                cert_path.chmod(0o644)
            except OSError:
                pass
            return True
        except Exception as exc:
            print(f"[Dashboard] HTTPS certificate generation failed: {exc}")
            return False

    def get_url(self) -> str:
        proto = "https" if self._ssl_enabled() else "http"
        return f"{proto}://{self._ip}:{PORT}"

    def get_manual_url(self) -> str:
        """URL for manual browser entry. When HTTPS active, points to alias port (also HTTPS)."""
        if self._ssl_enabled():
            return f"{self._ip}:{PORT + 1}"
        return f"{self._ip}:{PORT}"

    def _aes_key(self, session_key: str) -> bytes:
        if session_key not in self._aes_cache:
            self._aes_cache[session_key] = _derive_key(session_key)
        return self._aes_cache[session_key]

    def _decrypt(self, token: str, enc_b64: str) -> str | None:
        sk = self._token_keys.get(token)
        if not sk:
            return None
        try:
            return _decrypt_cbc(self._aes_key(sk), enc_b64)
        except Exception:
            return None

    # ── callbacks ────────────────────────────────────────────────────────

    def set_wake_callback(self, fn) -> None:
        self._wake_callback = fn

    def set_connect_callback(self, fn) -> None:
        self._connect_callback = fn

    # ── broadcast ────────────────────────────────────────────────────────

    async def broadcast(self, msg: dict) -> None:
        self._history.append(msg)
        if len(self._history) > 300:
            self._history = self._history[-300:]
        dead: set[WebSocket] = set()
        for ws in list(self._clients):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    # ── FastAPI app ───────────────────────────────────────────────────────

    def _build_app(self) -> "FastAPI":
        app = FastAPI(docs_url=None, redoc_url=None)

        def _auth(req: Request) -> bool:
            tok = req.headers.get("authorization", "").removeprefix("Bearer ").strip()
            return bool(tok) and tok in self._tokens

        # serve CryptoJS from local cache, fallback to CDN redirect
        @app.get("/static/crypto.js")
        async def serve_crypto():
            if _CRYPTOJS_FILE.exists():
                return FileResponse(str(_CRYPTOJS_FILE),
                                    media_type="application/javascript")
            from fastapi.responses import RedirectResponse
            return RedirectResponse(_CRYPTOJS_CDN)

        @app.get("/login", response_class=HTMLResponse)
        async def login_page():
            return HTMLResponse(self._login_html)

        @app.get("/", response_class=HTMLResponse)
        async def index():
            # Auth is handled client-side via sessionStorage bearer token.
            # Server-side header auth can't work here because browser navigations
            # don't send custom headers (location.href doesn't carry Authorization).
            html = (self._app_html
                    .replace("__IP__", self._ip)
                    .replace("__PORT__", str(PORT)))
            return HTMLResponse(html)

        @app.post("/login")
        async def login(req: Request):
            body    = await req.json()
            entered = str(body.get("pin", "")).strip().upper()
            now     = time.time()
            if entered in self._pending_keys and self._pending_keys[entered] > now:
                del self._pending_keys[entered]          # one-time use
                tok = secrets.token_urlsafe(32)
                self._tokens.add(tok)
                self._token_keys[tok] = entered
                self._aes_key(entered)                   # pre-derive & cache
                if self._connect_callback:
                    self._connect_callback()
                asyncio.create_task(self.broadcast(
                    {"type": "sys", "text": "Remote connection established."}
                ))
                # Bearer token in response body — no cookies needed (works on any browser/HTTP)
                return JSONResponse({"ok": True, "token": tok})
            return JSONResponse({"ok": False, "error": "Invalid or expired key"},
                                status_code=401)

        @app.get("/auto-login")
        async def auto_login(key: str = ""):
            """QR code target — validates one-time key, creates session, redirects phone."""
            now = time.time()
            if not key or key not in self._pending_keys or self._pending_keys[key] <= now:
                return HTMLResponse("""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width">
<style>
  body{background:#07090f;color:#dde3ed;font-family:sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}
  h2{color:#f87171;margin-bottom:12px}p{color:#5e6a7e;font-size:14px}
</style></head>
<body><div><h2>Link Expired</h2>
<p>Press <strong style="color:#dde3ed">Remote Control</strong> in SAM to get a new QR code.</p>
</div></body></html>""")

            del self._pending_keys[key]
            tok     = secrets.token_urlsafe(32)
            dev_tok = secrets.token_urlsafe(32)
            self._tokens.add(tok)
            self._token_keys[tok] = key
            self._aes_key(key)
            self._device_sessions[dev_tok] = {"session_key": key}

            if self._connect_callback:
                self._connect_callback()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Remote connection established via QR code."}
            ))

            return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width">
<style>
  body{{background:#07090f;color:#dde3ed;font-family:sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}}
  p{{color:#5e6a7e;font-size:14px}}
</style></head>
<body>
<script>
  sessionStorage.setItem('sam_token','{tok}');
  sessionStorage.setItem('sam_key','{key}');
  localStorage.setItem('sam_device_token','{dev_tok}');
  setTimeout(function(){{location.replace('/')}},400);
</script>
<p>Connecting to SAM…</p>
</body></html>""")

        @app.post("/api/device-login")
        async def device_login_ep(req: Request):
            """Return a fresh auth token for a previously paired device token."""
            try:
                body = await req.json()
            except Exception:
                return JSONResponse({"ok": False}, status_code=400)
            dev_tok = (body.get("device_token") or "").strip()
            if not dev_tok or dev_tok not in self._device_sessions:
                return JSONResponse({"ok": False}, status_code=401)
            session_key = self._device_sessions[dev_tok]["session_key"]
            tok = secrets.token_urlsafe(32)
            self._tokens.add(tok)
            self._token_keys[tok] = session_key
            self._aes_key(session_key)
            if self._connect_callback:
                self._connect_callback()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Known device reconnected automatically."}
            ))
            return JSONResponse({"ok": True, "token": tok, "key": session_key})

        @app.post("/api/revoke-devices")
        async def revoke_devices(req: Request):
            """Invalidate all persistent device tokens (admin action)."""
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            count = len(self._device_sessions)
            self._device_sessions.clear()
            return JSONResponse({"ok": True, "revoked": count})

        @app.get("/api/device")
        async def device_info(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            import platform
            try:
                from core import llm_client
                provider = llm_client.get_llm_provider()
                _, model = llm_client.get_llm_settings()
            except Exception:
                provider, model = "unknown", "unknown"
            return JSONResponse({"os": platform.system(), "device": platform.machine(), "provider": provider, "model": model})

        @app.get("/api/preferences")
        async def get_preferences(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            return JSONResponse(self._user_data["preferences"])

        @app.post("/api/preferences")
        async def save_preferences(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            body = await req.json()
            salutation = body.get("salutation", "Sir")
            if salutation not in ("Sir", "Ma'am", "Other"):
                return JSONResponse({"error": "Invalid salutation"}, status_code=400)
            prefs = {"salutation": salutation, "other_name": str(body.get("other_name", "")).strip()[:80], "auto_open_bionic": bool(body.get("auto_open_bionic", True))}
            with self._user_data_lock:
                self._user_data["preferences"] = prefs
                self._save_user_data()
            if prefs["auto_open_bionic"]:
                self._launch_bionic()
            return JSONResponse(prefs)

        @app.get("/api/history")
        async def get_history(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            return JSONResponse({"entries": self._user_data.get("history", [])[-100:]})

        @app.post("/api/chat")
        async def chat_ep(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            body = await req.json()
            prompt = str(body.get("prompt", "")).strip()[:10000]
            if not prompt:
                return JSONResponse({"error": "Enter a prompt"}, status_code=400)
            prefs = self._user_data.get("preferences", {})
            form_of_address = (prefs.get("other_name") or "the user") if prefs.get("salutation") == "Other" else prefs.get("salutation", "Sir")
            recent = [e for e in self._user_data.get("history", []) if e.get("kind") in ("prompt", "output")][-6:]
            context = "\n".join(f"{e.get('kind')}: {str(e.get('text', ''))[:700]}" for e in recent)
            file_context = self._recent_file_context()
            web_context = ""
            web_results = []
            try:
                from actions.web_search import _web_scrape, _format_scraped
                web_results = await asyncio.wait_for(asyncio.to_thread(_web_scrape, prompt, 2), timeout=6)
                web_context = _format_scraped(prompt, web_results) if web_results else ""
            except Exception as exc:
                print(f"[Dashboard] Web lookup unavailable for this prompt: {exc}")
            system = f"Address the user as {form_of_address}. Give a direct, concise answer by default. Use live web findings when relevant and cite source URLs. Use prior context and uploaded files when useful."
            pieces = ([f"Earlier context:\n{context}"] if context else []) + ([f"Uploaded file contents:\n{file_context}"] if file_context else []) + ([f"Live web search results:\n{web_context}"] if web_context else []) + [f"Current request: {prompt}"]
            contextual_prompt = "\n\n".join(pieces)
            try:
                from core.brain_router import call_brain
                routed = await asyncio.to_thread(call_brain, contextual_prompt, system=system, task_type="auto", timeout=120)
                answer = str(routed.get("content", "")).strip()
                backend = str(routed.get("backend", "available model"))
            except Exception as exc:
                return JSONResponse({"error": f"Assistant request failed: {exc}"}, status_code=503)
            self._record({"kind": "prompt", "text": prompt})
            if context:
                self._record({"kind": "context", "text": context[:12000]})
            self._record({"kind": "output", "text": answer})
            return JSONResponse({"response": answer, "model": backend, "sources": web_results})

        @app.post("/api/browse")
        async def browse_ep(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            body = await req.json()
            query = str(body.get("query", "")).strip()[:2000]
            if not query:
                return JSONResponse({"error": "Enter a search prompt"}, status_code=400)
            try:
                from actions.web_search import _web_scrape, _format_scraped
                sources = await asyncio.to_thread(_web_scrape, query, 3)
                answer = _format_scraped(query, sources)
            except Exception as exc:
                return JSONResponse({"error": f"Browse failed: {exc}"}, status_code=503)
            self._record({"kind": "prompt", "mode": "browse", "text": query})
            self._record({"kind": "output", "mode": "browse", "text": answer})
            return JSONResponse({"response": answer, "sources": sources})

        @app.post("/api/command")
        async def command(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            body  = await req.json()
            token = req.headers.get("authorization", "").removeprefix("Bearer ").strip()
            enc   = body.get("enc", "")
            if enc:
                text = self._decrypt(token, enc)
                if text is None:
                    return JSONResponse({"error": "Decryption failed"}, status_code=400)
            else:
                text = (body.get("text") or "").strip()
            if text:
                await self._command_queue.put(text)
                if self._wake_callback:
                    self._wake_callback()
            return JSONResponse({"ok": True})

        @app.post("/api/vision")
        async def vision_ep(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                body = await req.json()
                image = str(body.get("image", ""))
                prompt = str(body.get("prompt", "Describe this image.")).strip()[:1000]
                if not image.startswith("data:image/") or "," not in image:
                    return JSONResponse({"error": "A webcam image is required"}, status_code=400)
                mime, encoded = image[5:].split(";base64,", 1)
                raw = base64.b64decode(encoded, validate=True)
                if len(raw) > 5_000_000:
                    return JSONResponse({"error": "Image is too large"}, status_code=413)
                from core import llm_client
                import ipaddress
                from urllib.parse import urlparse
                provider = llm_client.get_llm_provider()
                url, model = llm_client.get_llm_settings()
                host = (urlparse(url).hostname or "").lower()
                try:
                    local_host = host == "localhost" or ipaddress.ip_address(host).is_loopback
                except ValueError:
                    local_host = False
                if not local_host:
                    return JSONResponse({"error": "Webcam frames are sent only to a loopback local model URL. Set llm_url to localhost or 127.0.0.1."}, status_code=400)
                import requests
                encoded_image = base64.b64encode(raw).decode("ascii")
                if provider == "ollama":
                    endpoint = f"{url}/api/chat"
                    payload = {"model": model, "stream": False, "messages": [{"role": "user", "content": prompt, "images": [encoded_image]}]}
                else:
                    endpoint = f"{url}/v1/chat/completions"
                    payload = {"model": model, "stream": False, "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded_image}"}}]}]}
                def _ask_local():
                    response = requests.post(endpoint, json=payload, timeout=120)
                    response.raise_for_status()
                    data = response.json()
                    if provider == "ollama":
                        return data.get("message", {}).get("content", "").strip()
                    return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                answer = await asyncio.to_thread(_ask_local)
                self._record({"kind": "prompt", "mode": "camera", "text": prompt})
                self._record({"kind": "output", "mode": "camera", "text": answer})
                return JSONResponse({"response": answer})
            except Exception as e:
                return JSONResponse({"error": f"Local vision model unavailable: {e}"}, status_code=503)

        @app.post("/api/wake")
        async def wake_ep(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            if self._wake_callback:
                self._wake_callback()
            return JSONResponse({"ok": True})

        # ── Phone mic real-time audio → Gemini Live ──────────────────────────

        @app.websocket("/ws/phone-audio")
        async def phone_audio_ws(websocket: WebSocket, token: str = ""):
            tok = token.strip()
            if not tok or tok not in self._tokens:
                await websocket.close(code=4001)
                return
            await websocket.accept()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Phone microphone live."}
            ))
            try:
                while True:
                    data = await websocket.receive_bytes()
                    try:
                        self._phone_audio_queue.put_nowait(
                            {"data": data, "mime_type": "audio/pcm"}
                        )
                    except asyncio.QueueFull:
                        pass  # drop frame rather than block
            except WebSocketDisconnect:
                pass
            finally:
                asyncio.create_task(self.broadcast(
                    {"type": "sys", "text": "Phone microphone stopped."}
                ))

        # ── File sharing ──────────────────────────────────────────────────────

        def _safe_filename(raw: str) -> str:
            name = Path(raw).name                          # strip path components
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(". ")
            return name or "upload"

        if _UPLOAD_OK:
            @app.post("/api/upload")
            async def upload_file(req: Request, file: UploadFile = FastAPIFile(...), relative_path: str = FastAPIForm("")):
                if not _auth(req):
                    return JSONResponse({"error": "Unauthorized"}, status_code=401)

                safe = _safe_filename(file.filename or "upload")
                parts = [_safe_filename(part) for part in re.split(r"[/\\]+", relative_path) if part.strip(". ")]
                dest_dir = self._uploads_dir.joinpath(*parts[:-1]) if len(parts) > 1 else self._uploads_dir
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / (parts[-1] if parts else safe)
                if not dest.resolve().is_relative_to(self._uploads_dir.resolve()):
                    return JSONResponse({"error": "Invalid relative file path"}, status_code=400)
                stem, suffix = dest.stem, dest.suffix
                counter = 1
                while dest.exists():
                    dest = dest_dir / f"{stem}_{counter}{suffix}"
                    counter += 1

                size = 0
                max_bytes = MAX_UPLOAD_MB * 1024 * 1024
                try:
                    with open(dest, "wb") as fout:
                        while True:
                            chunk = await file.read(65536)
                            if not chunk:
                                break
                            size += len(chunk)
                            if size > max_bytes:
                                fout.close()
                                dest.unlink(missing_ok=True)
                                return JSONResponse(
                                    {"error": f"File too large (max {MAX_UPLOAD_MB} MB)"},
                                    status_code=413,
                                )
                            fout.write(chunk)
                except Exception as exc:
                    try:
                        dest.unlink(missing_ok=True)
                    except Exception:
                        pass
                    return JSONResponse({"error": str(exc)}, status_code=500)

                relative = dest.relative_to(self._uploads_dir).as_posix()
                self._record({"kind": "file", "name": dest.name, "path": relative, "size": size})
                asyncio.create_task(self.broadcast({
                    "type": "file_received",
                    "name": dest.name,
                    "path": relative,
                    "size": size,
                    "saved_to": str(self._uploads_dir),
                }))
                return JSONResponse({"ok": True, "name": dest.name, "path": relative, "size": size})
        else:
            @app.post("/api/upload")
            async def upload_unavailable(req: Request):
                return JSONResponse(
                    {"error": "File uploads require: pip install python-multipart"},
                    status_code=503,
                )

        @app.get("/api/files")
        async def list_files(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            files = []
            try:
                for f in sorted(
                    (p for p in self._uploads_dir.rglob("*") if p.is_file()),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                ):
                    files.append({"name": f.name, "path": f.relative_to(self._uploads_dir).as_posix(), "size": f.stat().st_size})
            except Exception:
                pass
            return JSONResponse({"files": files})

        @app.get("/uploads/{filename:path}")
        async def download_file(filename: str, token: str = ""):
            # Auth via query param — browser <a download> can't send custom headers
            tok = token.strip()
            if not tok or tok not in self._tokens:
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            parts = [_safe_filename(part) for part in re.split(r"[/\\]+", filename) if part.strip(". ")]
            path = self._uploads_dir.joinpath(*parts)
            if not parts or not path.resolve().is_relative_to(self._uploads_dir.resolve()) or not path.exists() or not path.is_file():
                return JSONResponse({"error": "Not found"}, status_code=404)
            return FileResponse(str(path), filename=path.name)

        @app.websocket("/ws")
        async def ws_ep(websocket: WebSocket, token: str = ""):
            tok = token.strip()
            if not tok or tok not in self._tokens:
                await websocket.close(code=4001)
                return
            await websocket.accept()
            self._clients.add(websocket)
            for entry in self._history[-50:]:
                try:
                    await websocket.send_json(entry)
                except Exception:
                    break
            try:
                while True:
                    data = await websocket.receive_json()
                    if data.get("type") == "command":
                        enc = data.get("enc", "")
                        t   = self._decrypt(tok, enc) if enc else (data.get("text") or "").strip()
                        if t:
                            await self._command_queue.put(t)
                            if self._wake_callback:
                                self._wake_callback()
            except WebSocketDisconnect:
                pass
            finally:
                self._clients.discard(websocket)

        return app

    # ── serve ─────────────────────────────────────────────────────────────

    async def _serve_alias(self) -> None:
        """Second HTTPS server on PORT+1 sharing the same app and in-memory state.
        Chrome HTTPS-upgrades any bare IP:PORT the user types, so this port also needs TLS.
        User types IP:8001 → Chrome tries https → self-signed cert warning → accept once → done."""
        ssl_key  = BASE_DIR / "config" / "certs" / "sam.key"
        ssl_cert = BASE_DIR / "config" / "certs" / "sam.crt"
        asyncio.get_event_loop().run_in_executor(None, _ensure_network_access, PORT + 1)
        cfg = uvicorn.Config(
            self.app, host="0.0.0.0", port=PORT + 1, log_level="warning",
            ssl_keyfile=str(ssl_key), ssl_certfile=str(ssl_cert),
        )
        print(f"[Dashboard] Manual entry:  {self._ip}:{PORT + 1}  (type in browser, accept cert once)")
        await uvicorn.Server(cfg).serve()

    async def serve(self) -> None:
        if not _DEPS_OK:
            print("[Dashboard] fastapi/uvicorn not installed — dashboard disabled.")
            print("[Dashboard] Run:  pip install fastapi 'uvicorn[standard]' cryptography")
            return

        self._launch_bionic()

        # Firewall setup runs in a thread — uvicorn starts immediately,
        # no waiting for UAC dialogs or subprocess timeouts.
        asyncio.get_event_loop().run_in_executor(None, _ensure_network_access, PORT)

        # HTTPS is enabled by default for LAN dashboard traffic. A self-signed
        # certificate is generated locally on first use; if cryptography or
        # certificate generation is unavailable, fall back to HTTP rather than
        # preventing SAM itself from starting.
        use_https = True
        try:
            import json as _json
            cfg_path = BASE_DIR / "config" / "api_keys.json"
            cfg = _json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
            use_https = bool(cfg.get("dashboard_https", True))
        except Exception:
            pass
        if use_https and not self._ssl_enabled():
            self._ensure_ssl_certs()
        use_ssl  = use_https and self._ssl_enabled()
        ssl_key  = BASE_DIR / "config" / "certs" / "sam.key"
        ssl_cert = BASE_DIR / "config" / "certs" / "sam.crt"

        if use_ssl:
            asyncio.create_task(self._serve_alias())

        cfg = uvicorn.Config(
            self.app, host="0.0.0.0", port=PORT, log_level="warning",
            **({"ssl_keyfile": str(ssl_key), "ssl_certfile": str(ssl_cert)} if use_ssl else {}),
        )

        proto = "https" if use_ssl else "http"
        print(f"[Dashboard] {proto}://{self._ip}:{PORT}")
        print("[Dashboard] Press 'Remote Control' in SAM UI to get the QR code.")
        await uvicorn.Server(cfg).serve()
