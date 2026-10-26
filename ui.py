from __future__ import annotations

import colorsys
import json
import math
import os
import platform
import random
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import psutil

if platform.system() == "Windows":
    _WIN_HIDE: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
else:
    _WIN_HIDE: dict = {}

from PyQt6.QtCore import (
    QEvent,
    QObject,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QImage,
    QKeyEvent,
    QKeySequence,
    QLinearGradient,
    QNativeGestureEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QShortcut,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QComboBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR   = _base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"


def _read_full_config() -> dict:
    try:
        if API_FILE.exists():
            return json.loads(API_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


_DEFAULT_W, _DEFAULT_H = 1100, 760
_MIN_W,     _MIN_H     = 900, 640
_LEFT_W  = 174
_RIGHT_W = 370

_OS = platform.system()


class C:
    """Hyper-futuristic cyber palette."""
    BG        = "#030008"
    PANEL     = "#080112"
    PANEL2    = "#0f011d"
    BORDER    = "#350850"
    BORDER_B  = "#7b1fa2"
    BORDER_A  = "#530d74"
    PRI       = "#a855f7"       # Neon Violet
    PRI_DIM   = "#6b21a8"
    PRI_GHO   = "#200038"
    CYAN      = "#00f0ff"       # High-tech Cyan
    ACC       = "#ff007f"       # Hot Plasma Pink
    ACC2      = "#ffaa00"       # Cyber Amber
    GREEN     = "#00ff9d"       # Toxic Matrix Green
    GREEN_D   = "#008f58"
    RED       = "#ff0055"       # Alert Red
    MUTED_C   = "#ff1744"
    TEXT      = "#d8b4fe"
    TEXT_DIM  = "#7e45b0"
    TEXT_MED  = "#a875d6"
    WHITE     = "#f3e8ff"
    DARK      = "#05000c"
    BAR_BG    = "#140022"


_HUE_LINKED = (
    "BG", "PANEL", "PANEL2", "BORDER", "BORDER_B", "BORDER_A",
    "PRI", "PRI_DIM", "PRI_GHO", "TEXT", "TEXT_DIM", "TEXT_MED",
    "WHITE", "DARK", "BAR_BG",
)
_PALETTE_DEFAULTS: dict[str, str] = {k: getattr(C, k) for k in _HUE_LINKED}
DEFAULT_UI_COLOR = _PALETTE_DEFAULTS["PRI"]


def apply_ui_accent(accent_hex: str) -> bool:
    accent_hex = (accent_hex or "").strip().lower()
    if not (accent_hex.startswith("#") and len(accent_hex) == 7):
        return False
    try:
        int(accent_hex[1:], 16)
    except ValueError:
        return False

    def _hsv(h: str) -> tuple[float, float, float]:
        r = int(h[1:3], 16) / 255
        g = int(h[3:5], 16) / 255
        b = int(h[5:7], 16) / 255
        return colorsys.rgb_to_hsv(r, g, b)

    base_h = _hsv(_PALETTE_DEFAULTS["PRI"])[0]
    acc_h, acc_s, _ = _hsv(accent_hex)
    dh   = acc_h - base_h
    grey = acc_s < 0.08

    for key, hex0 in _PALETTE_DEFAULTS.items():
        h, s, v = _hsv(hex0)
        if grey:
            s *= 0.15
        r, g, b = colorsys.hsv_to_rgb((h + dh) % 1.0, s, v)
        setattr(C, key, "#{:02x}{:02x}{:02x}".format(
            int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5)))
    return True


def current_palette() -> dict[str, str]:
    return {k: getattr(C, k) for k in _HUE_LINKED}


def retheme_all_widgets(old: dict[str, str], new: dict[str, str]) -> None:
    mapping = {old[k]: new[k] for k in old if old[k].lower() != new.get(k, old[k]).lower()}
    if not mapping:
        return
    app = QApplication.instance()
    if app is None:
        return

    pattern = re.compile("|".join(re.escape(k) for k in mapping.keys()), re.IGNORECASE)

    def _replace(match):
        val = match.group(0).lower()
        for k, v in mapping.items():
            if k.lower() == val:
                return v
        return match.group(0)

    for w in app.allWidgets():
        try:
            ss = w.styleSheet()
            if ss:
                new_ss = pattern.sub(_replace, ss)
                if new_ss != ss:
                    w.setStyleSheet(new_ss)
            w.update()
        except Exception:
            pass


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h)
    c.setAlpha(a)
    return c


# ── System Metrics ────────────────────────────────────────────────────────────
class _SysMetrics:
    def __init__(self):
        self.cpu  = 0.0
        self.mem  = 0.0
        self.net  = 0.0
        self.gpu  = -1.0
        self.tmp  = -1.0
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self._running:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(1.5)

    def _update(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent
        nc  = psutil.net_io_counters()
        now = time.time()
        dt  = now - self._last_net_t
        if dt > 0:
            sent = (nc.bytes_sent - self._last_net.bytes_sent) / dt
            recv = (nc.bytes_recv - self._last_net.bytes_recv) / dt
            net  = (sent + recv) / (1024 * 1024)
        else:
            net = 0.0
        self._last_net   = nc
        self._last_net_t = now

        gpu = -1.0
        tmp = -1.0
        try:
            temps = psutil.sensors_temperatures()
            for name in ["coretemp", "k10temp", "cpu_thermal", "acpitz"]:
                if name in temps and temps[name]:
                    tmp = temps[name][0].current
                    break
        except Exception:
            pass

        with self._lock:
            self.cpu = cpu
            self.mem = mem
            self.net = net
            self.gpu = gpu
            self.tmp = tmp

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu, "mem": self.mem, "net": self.net,
                "gpu": self.gpu, "tmp": self.tmp,
            }


_metrics = _SysMetrics()


# ── Chamfered Cybernetic Panel Frame ──────────────────────────────────────────
class CyberPanel(QWidget):
    """Futuristic container with 45-degree chamfered corners and neon brackets."""
    def __init__(self, tag: str = "", parent=None):
        super().__init__(parent)
        self._tag = tag
        self._font_scale = 1.0
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def set_zoom_factor(self, factor: float):
        self._font_scale = factor
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        cut = 14

        path = QPainterPath()
        path.moveTo(cut, 0)
        path.lineTo(W - cut, 0)
        path.lineTo(W, cut)
        path.lineTo(W, H - cut)
        path.lineTo(W - cut, H)
        path.lineTo(cut, H)
        path.lineTo(0, H - cut)
        path.lineTo(0, cut)
        path.closeSubpath()

        # Background
        p.fillPath(path, QBrush(qcol(C.PANEL, 245)))

        # Outer border
        p.setPen(QPen(qcol(C.BORDER, 190), 1))
        p.drawPath(path)

        # Highlight corner brackets
        p.setPen(QPen(qcol(C.PRI, 240), 2))
        p.drawLine(QPointF(0, cut), QPointF(cut, 0))
        p.drawLine(QPointF(cut, 0), QPointF(cut + 18, 0))

        p.drawLine(QPointF(W - cut, 0), QPointF(W, cut))
        p.drawLine(QPointF(W - cut - 18, 0), QPointF(W - cut, 0))

        p.drawLine(QPointF(0, H - cut), QPointF(cut, H))
        p.drawLine(QPointF(cut, H), QPointF(cut + 18, H))

        p.drawLine(QPointF(W, H - cut), QPointF(W - cut, H))
        p.drawLine(QPointF(W - cut - 18, H), QPointF(W - cut, H))

        if self._tag:
            pt = max(6, int(round(7 * getattr(self, "_font_scale", 1.0))))
            p.setFont(QFont("Courier New", pt, QFont.Weight.Bold))
            p.setPen(QPen(qcol(C.CYAN), 1))
            p.drawText(QRectF(cut + 8, 4, W - cut * 2, max(14, int(round(14 * getattr(self, "_font_scale", 1.0))))),
                       Qt.AlignmentFlag.AlignLeft, f"// {self._tag} //")


# ── Hyper-Futuristic Arc Reactor & 3D Parallax HUD ────────────────────────────
class HudCanvas(QWidget):
    def __init__(self, face_path: str, assistant_name: str = "S.A.M", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMouseTracking(True)
        self.setMinimumSize(340, 340)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.muted    = False
        self.speaking = False
        self.state    = "INITIALISING"
        self._assistant_name = assistant_name

        self._tick       = 0
        self._scale      = 1.0
        self._tgt_scale  = 1.0
        self._halo       = 60.0
        self._tgt_halo   = 60.0
        self._last_t     = time.time()
        self._scan       = 0.0
        self._scan2      = 180.0
        self._gyro_a     = 0.0
        self._gyro_b     = 45.0
        self._gyro_c     = 90.0
        self._scanline_y = 0.0
        self._pulses: list[float] = [0.0, 50.0, 100.0]
        self._blink      = True
        self._blink_tick = 0
        self._particles: list[list[float]] = []

        # Mouse parallax
        self._mouse_x = 0.0
        self._mouse_y = 0.0
        self._par_x   = 0.0
        self._par_y   = 0.0

        # Click lock-on target
        self._lock_pos: QPointF | None = None
        self._lock_anim = 0.0

        self._face_px: QPixmap | None = None
        self._load_face(face_path)

        self._font_scale = 1.0
        self._zoom_overlay_text = ""
        self._zoom_overlay_alpha = 0.0

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(16)

    def set_zoom_factor(self, factor: float):
        self._font_scale = factor
        self.update()

    def show_zoom_indicator(self, text: str):
        self._zoom_overlay_text = text
        self._zoom_overlay_alpha = 1.0
        self.update()

    def _load_face(self, path: str):
        try:
            from PIL import Image, ImageDraw
            import io
            img = Image.open(path).convert("RGBA")
            sz  = min(img.size)
            img = img.resize((sz, sz), Image.LANCZOS)
            mk  = Image.new("L", (sz, sz), 0)
            ImageDraw.Draw(mk).ellipse((2, 2, sz - 2, sz - 2), fill=255)
            img.putalpha(mk)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap()
            px.loadFromData(buf.getvalue())
            self._face_px = px
        except Exception:
            self._face_px = None

    def mouseMoveEvent(self, e):
        self._mouse_x = e.position().x()
        self._mouse_y = e.position().y()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._lock_pos = e.position()
            self._lock_anim = 1.0

    def _step(self):
        self._tick += 1
        now = time.time()
        is_spk = self.speaking

        if now - self._last_t > (0.10 if is_spk else 0.4):
            if is_spk:
                self._tgt_scale = random.uniform(1.08, 1.18)
                self._tgt_halo  = random.uniform(180, 240)
            elif self.muted:
                self._tgt_scale = 0.99
                self._tgt_halo  = 20
            elif self.state == "THINKING":
                self._tgt_scale = random.uniform(1.02, 1.09)
                self._tgt_halo  = random.uniform(110, 150)
            else:
                self._tgt_scale = random.uniform(1.002, 1.012)
                self._tgt_halo  = random.uniform(55, 75)
            self._last_t = now

        sp = 0.40 if is_spk else 0.16
        self._scale += (self._tgt_scale - self._scale) * sp
        self._halo  += (self._tgt_halo  - self._halo)  * sp

        # Staggered gyro rotations
        g_spd = 2.5 if is_spk else 0.85
        self._gyro_a = (self._gyro_a + g_spd * 1.1) % 360
        self._gyro_b = (self._gyro_b - g_spd * 0.9) % 360
        self._gyro_c = (self._gyro_c + g_spd * 1.5) % 360
        self._scan   = (self._scan  + (4.5 if is_spk else 1.8)) % 360
        self._scan2  = (self._scan2 - (3.0 if is_spk else 1.2)) % 360

        # Scanlines
        self._scanline_y = (self._scanline_y + 1.2) % max(1, self.height())

        # Smooth mouse parallax interpolation
        W, H = max(1, self.width()), max(1, self.height())
        target_px = (self._mouse_x - W / 2) / (W / 2) if self._mouse_x else 0.0
        target_py = (self._mouse_y - H / 2) / (H / 2) if self._mouse_y else 0.0
        self._par_x += (target_px - self._par_x) * 0.12
        self._par_y += (target_py - self._par_y) * 0.12

        # Lock-on animation decay
        if self._lock_anim > 0:
            self._lock_anim = max(0.0, self._lock_anim - 0.015)
            if self._lock_anim == 0:
                self._lock_pos = None

        # Zoom notification overlay decay
        if getattr(self, "_zoom_overlay_alpha", 0.0) > 0:
            self._zoom_overlay_alpha = max(0.0, self._zoom_overlay_alpha - 0.02)

        fw  = min(W, H)
        lim = fw * 0.72
        spd = 5.0 if is_spk else 2.2
        self._pulses = [r + spd for r in self._pulses if r + spd < lim]
        if len(self._pulses) < 3 and random.random() < (0.08 if is_spk else 0.03):
            self._pulses.append(0.0)

        # Particle ejections
        if (is_spk or self.state == "THINKING") and random.random() < 0.35:
            cx, cy = W / 2, H / 2
            ang = random.uniform(0, 2 * math.pi)
            r_s = fw * 0.22
            spd = random.uniform(1.5, 3.8)
            self._particles.append([
                cx + math.cos(ang) * r_s, cy + math.sin(ang) * r_s,
                math.cos(ang) * spd, math.sin(ang) * spd, 1.0,
            ])
        self._particles = [
            [p[0]+p[2], p[1]+p[3], p[2]*0.97, p[3]*0.97, p[4]-0.025]
            for p in self._particles if p[4] > 0
        ]

        self._blink_tick += 1
        if self._blink_tick >= 32:
            self._blink = not self._blink
            self._blink_tick = 0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), qcol(C.BG))

        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        fw = min(W, H)
        is_spk = self.speaking

        # ── Parallax Shifts ───────────────────────────────────────────────────
        bg_dx, bg_dy   = self._par_x * 8,  self._par_y * 8
        mid_dx, mid_dy = self._par_x * 16, self._par_y * 16
        fg_dx, fg_dy   = self._par_x * 24, self._par_y * 24

        # ── Background Tech Grid ──────────────────────────────────────────────
        p.setPen(QPen(qcol(C.PRI_GHO, 130), 1))
        step = 44
        ox = int(bg_dx) % step
        oy = int(bg_dy) % step
        for x in range(ox, W, step):
            p.drawLine(x, 0, x, H)
        for y in range(oy, H, step):
            p.drawLine(0, y, W, y)

        # ── Corner Real-Time Telemetry HUD Readouts ───────────────────────────
        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        # Top-Left
        p.setPen(QPen(qcol(C.CYAN), 1))
        p.drawText(QRectF(14, 12, 220, 48), Qt.AlignmentFlag.AlignLeft,
                   f"GEO_LOC // 37°46'N 122°25'W\n"
                   f"ELEV: 412M  ·  BEARING: {(self._tick * 2) % 360:03d}°\n"
                   f"PARALLAX: [{self._par_x:+.2f}, {self._par_y:+.2f}]")

        # Top-Right
        p.setPen(QPen(qcol(C.TEXT_MED), 1))
        p.drawText(QRectF(W - 234, 12, 220, 48), Qt.AlignmentFlag.AlignRight,
                   f"QUANTUM SYNC // 99.82%\n"
                   f"NEURAL MATRIX: 44.8 TFLOPS\n"
                   f"FRAME LATENCY: 16.4ms [60FPS]")

        # Bottom-Left
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(14, H - 54, 220, 48), Qt.AlignmentFlag.AlignLeft,
                   f"AUDIO_SPECT // 48.0 KHz\n"
                   f"BANDWIDTH: 1.24 GB/s\n"
                   f"RADIAL EQUALIZER: ACTIVE")

        # Bottom-Right
        p.setPen(QPen(qcol(C.GREEN if not self.muted else C.RED), 1))
        p.drawText(QRectF(W - 234, H - 54, 220, 48), Qt.AlignmentFlag.AlignRight,
                   f"DEFENSE // ALPHA-9 ACTIVE\n"
                   f"PROTOCOL: MARK XLIX\n"
                   f"STATUS: {'NOMINAL' if not self.muted else 'MUTED'}")

        # ── Concentric Glowing Halos ──────────────────────────────────────────
        r_face = fw * 0.28
        accent = C.MUTED_C if self.muted else (C.ACC if is_spk else C.PRI)
        for i in range(12):
            r   = r_face * (1.9 - i * 0.07)
            frc = 1.0 - i / 12
            a   = max(0, min(255, int(self._halo * 0.9 * (frc ** 2))))
            p.setPen(QPen(qcol(accent, a), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx + mid_dx - r, cy + mid_dy - r, r * 2, r * 2))

        # ── Pulse Shockwaves ──────────────────────────────────────────────────
        for pr in self._pulses:
            a   = max(0, int(240 * (1.0 - pr / (fw * 0.72))))
            p.setPen(QPen(qcol(accent, a), 1.5, Qt.PenStyle.DashLine))
            p.drawEllipse(QRectF(cx + mid_dx - pr, cy + mid_dy - pr, pr * 2, pr * 2))

        # ── 3D Gyroscopic Concentric Rings (Tilted by Mouse Parallax) ─────────
        p.save()
        p.translate(cx + mid_dx, cy + mid_dy)
        p.rotate(self._par_x * 8)

        # Gyro Ring A
        p.save()
        p.rotate(self._gyro_a)
        p.setPen(QPen(qcol(C.PRI, 210), 2))
        p.drawEllipse(QRectF(-fw * 0.44, -fw * 0.22, fw * 0.88, fw * 0.44))
        p.restore()

        # Gyro Ring B
        p.save()
        p.rotate(self._gyro_b)
        p.setPen(QPen(qcol(C.CYAN, 180), 1.5, Qt.PenStyle.DashLine))
        p.drawEllipse(QRectF(-fw * 0.38, -fw * 0.18, fw * 0.76, fw * 0.36))
        p.restore()

        # Gyro Ring C
        p.save()
        p.rotate(self._gyro_c)
        p.setPen(QPen(qcol(C.ACC, 200), 1.8))
        p.drawArc(QRectF(-fw * 0.46, -fw * 0.26, fw * 0.92, fw * 0.52), 0, 180 * 16)
        p.restore()
        p.restore()

        # ── Outer Radar Dial & Compass Degrees ────────────────────────────────
        rad_out = fw * 0.485
        rad_in  = fw * 0.462
        p.setPen(QPen(qcol(C.PRI, 180), 1))
        for deg in range(0, 360, 5):
            rad = math.radians(deg)
            is_cardinal = (deg % 90 == 0)
            is_major    = (deg % 30 == 0)
            inn = rad_in - (6 if is_cardinal else (3 if is_major else 0))
            p.drawLine(
                QPointF(cx + mid_dx + rad_out * math.cos(rad), cy + mid_dy - rad_out * math.sin(rad)),
                QPointF(cx + mid_dx + inn * math.cos(rad), cy + mid_dy - inn * math.sin(rad)),
            )

        # ── Sweeping Radar Beam ───────────────────────────────────────────────
        sweep_r = fw * 0.48
        sa = min(255, int(self._halo * 1.6))
        p.setPen(QPen(qcol(C.PRI, sa), 3))
        srect = QRectF(cx + mid_dx - sweep_r, cy + mid_dy - sweep_r, sweep_r * 2, sweep_r * 2)
        p.drawArc(srect, int(self._scan * 16), 55 * 16)

        # ── 360° Circular Orbital Audio Equalizer ─────────────────────────────
        orb_r_base = fw * 0.28
        num_bars = 48
        for i in range(num_bars):
            ang = (i / num_bars) * 2 * math.pi
            if self.muted:
                bar_len = 3
                b_col = qcol(C.MUTED_C, 160)
            elif is_spk:
                bar_len = random.randint(6, 28)
                b_col = qcol(C.ACC if bar_len > 18 else C.CYAN, 220)
            elif self.state == "THINKING":
                bar_len = int(8 + 6 * math.sin(self._tick * 0.2 + i * 0.5))
                b_col = qcol(C.ACC2, 200)
            else:
                bar_len = int(4 + 3 * math.sin(self._tick * 0.08 + i * 0.4))
                b_col = qcol(C.PRI, 150)

            x1 = cx + fg_dx + (orb_r_base) * math.cos(ang)
            y1 = cy + fg_dy + (orb_r_base) * math.sin(ang)
            x2 = cx + fg_dx + (orb_r_base + bar_len) * math.cos(ang)
            y2 = cy + fg_dy + (orb_r_base + bar_len) * math.sin(ang)

            p.setPen(QPen(b_col, 2))
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # ── Center Arc Reactor Core ───────────────────────────────────────────
        if self._face_px:
            fsz = int(fw * 0.54 * self._scale)
            scaled = self._face_px.scaled(
                fsz, fsz,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.drawPixmap(int(cx + fg_dx - fsz / 2), int(cy + fg_dy - fsz / 2), scaled)
        else:
            orb_r = int(fw * 0.23 * self._scale)
            oc = (255, 0, 85) if self.muted else ((255, 170, 0) if is_spk else (168, 85, 247))
            for i in range(10, 0, -1):
                r2  = int(orb_r * i / 10)
                frc = i / 10
                a   = max(0, min(255, int(self._halo * 1.3 * frc)))
                p.setBrush(QBrush(QColor(int(oc[0]*frc), int(oc[1]*frc), int(oc[2]*frc), a)))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QRectF(cx + fg_dx - r2, cy + fg_dy - r2, r2 * 2, r2 * 2))

            p.setPen(QPen(qcol(C.WHITE, 250), 1))
            name_pt = max(8, int(round(14 * getattr(self, "_font_scale", 1.0))))
            p.setFont(QFont("Courier New", name_pt, QFont.Weight.Bold))
            p.drawText(QRectF(cx + fg_dx - 90, cy + fg_dy - 12, 180, 24),
                       Qt.AlignmentFlag.AlignCenter, self._assistant_name)

        # ── Crosshairs & Floating Reticle ─────────────────────────────────────
        ch_r  = fw * 0.49
        gap_h = fw * 0.18
        p.setPen(QPen(qcol(C.CYAN, int(self._halo * 0.5)), 1))
        p.drawLine(QPointF(cx + fg_dx - ch_r, cy + fg_dy), QPointF(cx + fg_dx - gap_h, cy + fg_dy))
        p.drawLine(QPointF(cx + fg_dx + gap_h, cy + fg_dy), QPointF(cx + fg_dx + ch_r, cy + fg_dy))
        p.drawLine(QPointF(cx + fg_dx, cy + fg_dy - ch_r), QPointF(cx + fg_dx, cy + fg_dy - gap_h))
        p.drawLine(QPointF(cx + fg_dx, cy + fg_dy + gap_h), QPointF(cx + fg_dx, cy + fg_dy + ch_r))

        # ── Interactive Click-to-Target Reticle ────────────────────────────────
        if self._lock_pos and self._lock_anim > 0:
            lx, ly = self._lock_pos.x(), self._lock_pos.y()
            l_rad = 32 * (2.0 - self._lock_anim)
            l_alpha = int(255 * self._lock_anim)
            p.setPen(QPen(qcol(C.RED, l_alpha), 2))
            p.drawEllipse(QRectF(lx - l_rad, ly - l_rad, l_rad * 2, l_rad * 2))

            l_pt = max(6, int(round(7 * getattr(self, "_font_scale", 1.0))))
            p.setFont(QFont("Courier New", l_pt, QFont.Weight.Bold))
            p.setPen(QPen(qcol(C.RED, l_alpha), 1))
            p.drawText(QRectF(lx + l_rad + 6, ly - 8, 180, 16),
                       Qt.AlignmentFlag.AlignLeft, "TARGET ACQUIRED // DIST: 14.8M")

        # ── Cyber Status Badge ────────────────────────────────────────────────
        sy = cy + fg_dy + fw * 0.36
        if self.muted:
            txt, col = "⊘  MIC MUTED", qcol(C.MUTED_C)
        elif self.speaking:
            txt, col = "▲  TRANSMITTING", qcol(C.ACC)
        elif self.state == "THINKING":
            sym = "◈" if self._blink else "◇"
            txt, col = f"{sym}  ANALYZING QUERY", qcol(C.ACC2)
        elif self.state == "PROCESSING":
            sym = "▷" if self._blink else "▶"
            txt, col = f"{sym}  PROCESSING DATA", qcol(C.CYAN)
        elif self.state == "LISTENING":
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  HOT MIC LISTENING", qcol(C.GREEN)
        else:
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  {self.state}", qcol(C.PRI)

        bw = max(220, int(round(220 * max(1.0, getattr(self, "_font_scale", 1.0)))))
        bh = max(24, int(round(24 * max(1.0, getattr(self, "_font_scale", 1.0)))))
        p.setBrush(QBrush(qcol(C.PANEL2, 230)))
        p.setPen(QPen(col, 1))
        p.drawRoundedRect(QRectF(cx + fg_dx - bw / 2, sy, bw, bh), 4, 4)
        b_pt = max(7, int(round(9 * getattr(self, "_font_scale", 1.0))))
        p.setFont(QFont("Courier New", b_pt, QFont.Weight.Bold))
        p.drawText(QRectF(cx + fg_dx - bw / 2, sy, bw, bh), Qt.AlignmentFlag.AlignCenter, txt)

        # ── Futuristic Zoom Overlay Pill ──────────────────────────────────────
        if getattr(self, "_zoom_overlay_alpha", 0.0) > 0 and getattr(self, "_zoom_overlay_text", ""):
            z_alpha = int(255 * min(1.0, self._zoom_overlay_alpha))
            p.save()
            ow, oh = 180, 30
            ox, oy = (W - ow) / 2, 16
            p.setBrush(QBrush(QColor(8, 0, 18, min(240, int(z_alpha * 0.95)))))
            p.setPen(QPen(qcol(C.CYAN, z_alpha), 1.5))
            p.drawRoundedRect(QRectF(ox, oy, ow, oh), 6, 6)
            p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            p.setPen(QPen(qcol(C.WHITE, z_alpha), 1))
            p.drawText(QRectF(ox, oy, ow, oh), Qt.AlignmentFlag.AlignCenter, self._zoom_overlay_text)
            p.restore()

        # ── CRT Holographic Scanlines ─────────────────────────────────────────
        p.setPen(QPen(qcol(C.CYAN, 18), 1))
        for y in range(0, H, 4):
            p.drawLine(0, y, W, y)

        p.setPen(QPen(qcol(C.CYAN, 55), 2))
        p.drawLine(0, int(self._scanline_y), W, int(self._scanline_y))


# ── Discrete Segmented LED Telemetry Bar ──────────────────────────────────────
class SegmentedMetricBar(QWidget):
    """Futuristic aerospace segmented LED meter with digital readout."""
    def __init__(self, label: str, color: str = C.PRI, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._value = 0.0
        self._text  = "--"
        self._font_scale = 1.0
        self.setFixedHeight(42)
        self.setMinimumWidth(90)

    def set_zoom_factor(self, factor: float):
        self._font_scale = factor
        self.setFixedHeight(max(38, int(round(42 * min(1.25, factor)))))
        self.update()

    def set_value(self, pct: float, text: str):
        self._value = max(0.0, min(100.0, pct))
        self._text  = text
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        p.setBrush(QBrush(qcol(C.PANEL2)))
        p.setPen(QPen(qcol(C.BORDER), 1))
        p.drawRoundedRect(QRectF(1, 1, W - 2, H - 2), 4, 4)

        lbl_pt = max(6, int(round(7 * getattr(self, "_font_scale", 1.0))))
        p.setFont(QFont("Courier New", lbl_pt, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(8, 4, 75, 14), Qt.AlignmentFlag.AlignLeft, self._label)

        if self._value > 85:
            val_col = qcol(C.RED)
        elif self._value > 65:
            val_col = qcol(C.ACC2)
        else:
            val_col = qcol(self._color)

        val_pt = max(7, int(round(9 * getattr(self, "_font_scale", 1.0))))
        p.setFont(QFont("Courier New", val_pt, QFont.Weight.Bold))
        p.setPen(QPen(val_col if self._text != "--" else qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(0, 4, W - 8, 14), Qt.AlignmentFlag.AlignRight, self._text)

        # Segmented Ladder Bar
        segments = 18
        gap = 2
        bar_y = H - 12
        bar_h = 6
        avail_w = W - 16
        seg_w = max(2, (avail_w - (segments - 1) * gap) / segments)
        filled = int(round((self._value / 100.0) * segments))

        for i in range(segments):
            x = 8 + i * (seg_w + gap)
            rect = QRectF(x, bar_y, seg_w, bar_h)
            if i < filled:
                seg_col = qcol(C.RED) if i >= 15 else (qcol(C.ACC2) if i >= 11 else qcol(self._color))
                p.setBrush(QBrush(seg_col))
            else:
                p.setBrush(QBrush(qcol(C.BAR_BG)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(rect, 1, 1)


# ── Activity Log Terminal ─────────────────────────────────────────────────────
class LogWidget(QTextEdit):
    _sig = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self._font_scale = 1.0
        self.setFont(QFont("Courier New", 9))

    def set_zoom_factor(self, factor: float):
        self._font_scale = factor
        pt = max(6, int(round(9 * factor)))
        f = QFont("Courier New", pt)
        self.setFont(f)
        self.document().setDefaultFont(f)
        self.setStyleSheet(f"""
            QTextEdit {{
                background: {C.DARK};
                color: {C.TEXT};
                border: 1px solid {C.BORDER};
                border-radius: 4px;
                padding: 6px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{
                background: {C.BG}; width: 6px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B}; border-radius: 3px; min-height: 20px;
            }}
        """)
        self._queue: list[str] = []
        self._typing  = False
        self._text    = ""
        self._pos     = 0
        self._tag     = "sys"
        self._ai_name_lc = "sam"
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._sig.connect(self._enqueue)

    def append_log(self, text: str):
        self._sig.emit(text)

    def _enqueue(self, text: str):
        self._queue.append(text)
        if not self._typing:
            self._next()

    def _next(self):
        if not self._queue:
            self._typing = False
            return
        self._typing = True
        self._text   = self._queue.pop(0)
        self._pos    = 0
        tl = self._text.lower()
        _ai_pfx = f"{self._ai_name_lc}:"
        if   tl.startswith("you:"):                            self._tag = "you"
        elif tl.startswith(_ai_pfx) or tl.startswith("sam:"): self._tag = "ai"
        elif tl.startswith("file:"):                           self._tag = "file"
        elif "err" in tl:                                      self._tag = "err"
        else:                                                  self._tag = "sys"
        self._tmr.start(6)

    def _step(self):
        if self._pos < len(self._text):
            ch  = self._text[self._pos]
            cur = self.textCursor()
            fmt = cur.charFormat()
            col = {
                "you":  qcol(C.WHITE),
                "ai":   qcol(C.CYAN),
                "err":  qcol(C.RED),
                "file": qcol(C.GREEN),
                "sys":  qcol(C.ACC2),
            }.get(self._tag, qcol(C.TEXT))
            fmt.setForeground(QBrush(col))
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText(ch, fmt)
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            self._pos += 1
        else:
            self._tmr.stop()
            cur = self.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText("\n")
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            QTimer.singleShot(15, self._next)


# ── File Handling & Drop Zone ─────────────────────────────────────────────────
class FileDropZone(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._font_scale = 1.0
        self.setFixedHeight(84)
        self._current_files: list[str] = []
        self._hovering  = False
        self._drag_over = False
        self._dash_offset = 0.0

        self._anim_tmr = QTimer(self)
        self._anim_tmr.timeout.connect(self._animate)
        self._anim_tmr.start(40)

    def set_zoom_factor(self, factor: float):
        self._font_scale = factor
        self.setFixedHeight(max(70, int(round(84 * min(1.25, factor)))))
        self.update()

    def _animate(self):
        self._dash_offset = (self._dash_offset + 0.8) % 20
        self.update()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag_over = True
            self.update()

    def dragLeaveEvent(self, _):
        self._drag_over = False
        self.update()

    def dropEvent(self, e: QDropEvent):
        self._drag_over = False
        urls = e.mimeData().urls()
        paths = [url.toLocalFile() for url in urls if url.isLocalFile()]
        paths = [path for path in paths if Path(path).is_file()]
        if paths:
            self._set_files(paths)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if self._current_files and e.pos().x() > self.width() - 32:
                self.clear_file()
            else:
                self._browse()

    def enterEvent(self, _):
        self._hovering = True
        self.update()

    def leaveEvent(self, _):
        self._hovering = False
        self.update()

    def current_file(self) -> str | None:
        return self._current_files[0] if self._current_files else None

    def current_files(self) -> list[str]:
        return list(self._current_files)

    def clear_file(self):
        self._current_files = []
        self.update()

    def _browse(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select a file for S.A.M", str(Path.home()),
            "All Files (*.*);;Images (*.jpg *.jpeg *.png *.webp);;Documents (*.pdf *.docx *.txt *.md);;Audio (*.wav *.mp3 *.m4a *.aac *.ogg *.flac);;Code (*.py *.js *.html *.css)",
        )
        if paths:
            self._set_files(paths)

    def _set_file(self, path: str):
        self._set_files([path])

    def _set_files(self, paths: list[str]):
        self._current_files = list(dict.fromkeys(paths))[:10]
        self.update()
        for path in self._current_files:
            self.file_selected.emit(path)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        pad = 4
        rect = QRectF(pad, pad, W - pad * 2, H - pad * 2)

        bg = qcol(C.PRI_GHO if self._drag_over else (C.PANEL2 if self._hovering else C.PANEL))
        p.setBrush(QBrush(bg))
        border_col = qcol(C.GREEN if self._current_files else (C.CYAN if self._drag_over else (C.PRI if self._hovering else C.BORDER)))
        pen = QPen(border_col, 1.5, Qt.PenStyle.DashLine)
        pen.setDashOffset(self._dash_offset)
        p.setPen(pen)
        p.drawRoundedRect(rect, 4, 4)

        scale = getattr(self, "_font_scale", 1.0)
        if self._current_files:
            path = Path(self._current_files[0])
            p.setFont(QFont("Courier New", max(6, int(round(8 * scale))), QFont.Weight.Bold))
            p.setPen(QPen(qcol(C.WHITE), 1))
            name = path.name if len(path.name) <= 28 else path.name[:25] + "..."
            more = f"  +{len(self._current_files) - 1} MORE" if len(self._current_files) > 1 else ""
            p.drawText(QRectF(14, 18, W - 48, 16), Qt.AlignmentFlag.AlignLeft, f"📎 {name}{more}")

            p.setFont(QFont("Courier New", max(6, int(round(7 * scale)))))
            p.setPen(QPen(qcol(C.TEXT_DIM), 1))
            p.drawText(QRectF(14, 38, W - 48, 14), Qt.AlignmentFlag.AlignLeft,
                       f"{len(self._current_files)} FILE{'S' if len(self._current_files) != 1 else ''} ATTACHED · CLICK TO REPLACE")

            p.setFont(QFont("Courier New", max(8, int(round(10 * scale))), QFont.Weight.Bold))
            p.setPen(QPen(qcol(C.RED), 1))
            p.drawText(QRectF(W - 28, 0, 24, H), Qt.AlignmentFlag.AlignCenter, "✕")
        else:
            p.setFont(QFont("Courier New", max(6, int(round(8 * scale))), QFont.Weight.Bold))
            p.setPen(QPen(qcol(C.PRI if self._hovering else C.TEXT_MED), 1))
            p.drawText(QRectF(0, 22, W, 16), Qt.AlignmentFlag.AlignCenter, "◈  DROP FILE  /  CLICK TO BROWSE")
            p.setFont(QFont("Courier New", max(6, int(round(7 * scale)))))
            p.setPen(QPen(qcol(C.TEXT_DIM), 1))
            p.drawText(QRectF(0, 42, W, 14), Qt.AlignmentFlag.AlignCenter, "IMAGES · DOCS · CODE · ARCHIVES")


class CameraCaptureDialog(QDialog):
    """Desktop camera preview with still photo and microphone-enabled video capture."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PyQt6.QtCore import QUrl
        from PyQt6.QtMultimedia import (
            QAudioInput, QCamera, QImageCapture, QMediaCaptureSession,
            QMediaDevices, QMediaFormat, QMediaRecorder,
        )
        from PyQt6.QtMultimediaWidgets import QVideoWidget

        self._QUrl = QUrl
        cameras = list(QMediaDevices.videoInputs())
        self._camera = QMediaDevices.defaultVideoInput()
        if self._camera.isNull() and cameras:
            self._camera = cameras[0]
        if self._camera.isNull():
            raise RuntimeError("No camera was detected. Connect a camera and allow SAM camera access in system settings.")
        audio_device = QMediaDevices.defaultAudioInput()
        self._has_microphone = not audio_device.isNull()

        self.setWindowTitle("SAM Camera")
        self.resize(700, 520)
        root = QVBoxLayout(self)
        self._preview = QVideoWidget(self)
        self._preview.setMinimumSize(480, 360)
        root.addWidget(self._preview, 1)
        self._status = QLabel("Camera ready" if self._has_microphone else "Camera ready · no microphone detected; photos still work")
        root.addWidget(self._status)
        controls = QHBoxLayout()
        photo = QPushButton("Take photo")
        photo.clicked.connect(self._take_photo)
        self._record_button = QPushButton("Record video with sound")
        self._record_button.setEnabled(self._has_microphone)
        if not self._has_microphone:
            self._record_button.setToolTip("Connect or enable a microphone to record video with sound.")
        self._record_button.clicked.connect(self._toggle_video)
        close = QPushButton("Close camera")
        close.clicked.connect(self.close)
        controls.addWidget(photo)
        controls.addWidget(self._record_button)
        controls.addWidget(close)
        root.addLayout(controls)

        self._session = QMediaCaptureSession(self)
        self._camera_object = QCamera(self._camera, self)
        self._recorder = QMediaRecorder(self)
        self._recorder.setMediaFormat(QMediaFormat(QMediaFormat.FileFormat.MPEG4))
        self._image_capture = QImageCapture(self)
        self._session.setCamera(self._camera_object)
        if self._has_microphone:
            self._audio_input = QAudioInput(audio_device, self)
            self._session.setAudioInput(self._audio_input)
        self._session.setRecorder(self._recorder)
        self._session.setImageCapture(self._image_capture)
        self._session.setVideoOutput(self._preview)
        # Notify immediately when photo file is saved to disk
        try:
            self._image_capture.imageSaved.connect(
                lambda _id, path: self._status.setText(f"Photo saved: {Path(path).name}")
            )
        except Exception:
            pass
        try:
            self._recorder.recorderStateChanged.connect(self._on_recorder_state_changed)
        except Exception:
            pass
        # Some packaged Qt Multimedia backends expose the PyQt signal wrapper
        # without the matching C++ meta-object signal. Avoid connecting it:
        # that mismatch raises during dialog construction on macOS.
        self._image_capture.errorOccurred.connect(
            lambda _capture_id, _error, message: self._capture_error(message)
        )
        try:
            self._camera_object.errorOccurred.connect(
                lambda _error, message: self._camera_error(message)
            )
        except (AttributeError, TypeError):
            pass
        self._camera_object.start()

    def _capture_dir(self) -> Path:
        target = BASE_DIR / "memory" / "captures"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _take_photo(self):
        path = self._capture_dir() / f"photo-{int(time.time())}.jpg"
        self._image_capture.captureToFile(str(path))
        self._status.setText(f"Capturing {path.name}…")

    def _on_recorder_state_changed(self, state):
        from PyQt6.QtMultimedia import QMediaRecorder
        if state == QMediaRecorder.RecorderState.StoppedState:
            self._record_button.setText("Record video with sound")
            saved_name = getattr(self, "_record_path", None)
            if saved_name:
                self._status.setText(f"Video saved: {Path(saved_name).name}")
            else:
                self._status.setText("Camera ready")

    def _toggle_video(self):
        from PyQt6.QtMultimedia import QMediaRecorder
        if self._recorder.recorderState() == QMediaRecorder.RecorderState.RecordingState:
            self._recorder.stop()
            self._record_button.setText("Record video with sound")
            self._status.setText("Finalizing video…")
            return
        path = self._capture_dir() / f"video-{int(time.time())}.mp4"
        self._record_path = str(path)
        self._recorder.setOutputLocation(self._QUrl.fromLocalFile(str(path)))
        self._recorder.record()
        self._record_button.setText("Stop video recording")
        self._status.setText("Recording video with microphone sound…")
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(1000, self._check_record_error)

    def _check_record_error(self):
        message = self._recorder.errorString()
        if message:
            self._record_button.setText("Record video with sound")
            self._status.setText(f"Video recording error: {message}")

    def _record_error(self, message=""):
        self._record_button.setText("Record video with sound")
        self._status.setText(f"Video recording error: {message or self._recorder.errorString()}")

    def _capture_error(self, message=""):
        self._status.setText(f"Photo capture error: {message or self._image_capture.errorString()}")

    def _camera_error(self, message=""):
        detail = message or self._camera_object.errorString()
        self._status.setText(f"Camera error: {detail}. Check camera permission and close other apps using it.")

    def closeEvent(self, event):
        self._recorder.stop()
        self._camera_object.stop()
        super().closeEvent(event)


class VoiceOnlyRecorderDialog(QDialog):
    """Save a microphone-only recording as WAV without starting speech recognition."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stream = None
        self._chunks = []
        self._sample_rate = 16000
        self.setWindowTitle("SAM Voice-only Recording")
        root = QVBoxLayout(self)
        self._status = QLabel("Record microphone audio only; SAM will save a WAV file.")
        root.addWidget(self._status)
        self._record_button = QPushButton("Start voice-only recording")
        self._record_button.clicked.connect(self._toggle_recording)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        row = QHBoxLayout()
        row.addWidget(self._record_button)
        row.addWidget(close)
        root.addLayout(row)

    def _toggle_recording(self):
        if self._stream is not None:
            self._finish_recording()
            return
        try:
            import sounddevice as sd
            self._chunks = []
            self._sample_rate = int(sd.query_devices(kind="input")["default_samplerate"])
            def collect(indata, _frames, _time_info, _status):
                self._chunks.append(bytes(indata))
            self._stream = sd.InputStream(samplerate=self._sample_rate, channels=1, dtype="int16", callback=collect)
            self._stream.start()
            self._record_button.setText("Stop and save recording")
            self._status.setText("Recording voice only…")
        except Exception as exc:
            self._stream = None
            self._status.setText(f"Microphone recording could not start: {exc}")

    def _finish_recording(self):
        if self._stream is None:
            return
        self._stream.stop()
        self._stream.close()
        self._stream = None
        import wave
        target_dir = BASE_DIR / "memory" / "captures"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"voice-only-{int(time.time())}.wav"
        with wave.open(str(target), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(self._sample_rate)
            output.writeframes(b"".join(self._chunks))
        self._record_button.setText("Start voice-only recording")
        self._status.setText(f"Saved {target.name} in memory/captures")

    def closeEvent(self, event):
        if self._stream is not None:
            self._finish_recording()
        super().closeEvent(event)


class ChatHistoryDialog(QDialog):
    """Tactical Cyberpunk HUD dialog for reviewing, searching, and managing previous chats."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SAM — Previous Chat Transmissions")
        self.resize(750, 600)
        self.setStyleSheet(f"""
            QDialog {{
                background: #080012;
                border: 2px solid {C.CYAN};
                border-radius: 8px;
            }}
            QLabel {{
                color: {C.WHITE};
                background: transparent;
                font-family: 'Courier New';
            }}
            QLineEdit {{
                background: {C.PANEL2};
                color: {C.WHITE};
                border: 1px solid {C.BORDER_A};
                border-radius: 4px;
                padding: 6px 10px;
                font-family: 'Courier New';
                font-size: 11px;
            }}
            QLineEdit:focus {{
                border-color: {C.CYAN};
            }}
            QTextEdit {{
                background: #05000c;
                color: {C.WHITE};
                border: 1px solid {C.BORDER};
                border-radius: 4px;
                padding: 8px;
                font-family: 'Courier New';
                font-size: 11px;
            }}
            QPushButton {{
                background: {C.PANEL2};
                color: {C.CYAN};
                border: 1px solid {C.BORDER_A};
                border-radius: 4px;
                padding: 6px 14px;
                font-family: 'Courier New';
                font-size: 10px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {C.PRI_GHO};
                border-color: {C.CYAN};
                color: {C.WHITE};
            }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        # Header
        top_row = QHBoxLayout()
        hdr = QLabel("// PREVIOUS CONVERSATION TRANSMISSIONS //")
        hdr.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.CYAN};")
        top_row.addWidget(hdr)
        top_row.addStretch()

        self._count_lbl = QLabel("0 TRANSMISSIONS")
        self._count_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._count_lbl.setStyleSheet(f"color: {C.ACC2};")
        top_row.addWidget(self._count_lbl)
        lay.addLayout(top_row)

        # Filter row
        filter_row = QHBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("🔍 Filter transmissions by query keyword or timestamp...")
        self._search_input.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self._search_input, 1)

        refresh_btn = QPushButton("🔄 REFRESH")
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.clicked.connect(self._reload_chats)
        filter_row.addWidget(refresh_btn)
        lay.addLayout(filter_row)

        # Main viewer (rich HTML format)
        self._viewer = QTextEdit()
        self._viewer.setReadOnly(True)
        lay.addWidget(self._viewer, 1)

        # Bottom actions
        btn_row = QHBoxLayout()
        copy_btn = QPushButton("📋 COPY TRANSCRIPT")
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.clicked.connect(self._copy_all)
        btn_row.addWidget(copy_btn)

        clear_btn = QPushButton("🗑️ CLEAR HISTORY")
        clear_btn.setStyleSheet(f"color: {C.RED}; border-color: {C.RED};")
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.clicked.connect(self._clear_chats)
        btn_row.addWidget(clear_btn)

        btn_row.addStretch()

        close_btn = QPushButton("✕ CLOSE")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

        self._all_messages = []
        self._reload_chats()

    def _reload_chats(self):
        try:
            from memory.chat_history import load_messages
            self._all_messages = load_messages(limit=1000)
        except Exception:
            self._all_messages = []
        self._apply_filter(self._search_input.text())

    def _apply_filter(self, query: str = ""):
        q = (query or "").strip().lower()
        filtered = [
            m for m in self._all_messages
            if not q or q in m.get("content", "").lower() or q in m.get("timestamp", "").lower() or q in m.get("role", "").lower()
        ]
        self._count_lbl.setText(f"{len(filtered)} / {len(self._all_messages)} TRANSMISSIONS")

        if not filtered:
            self._viewer.setHtml("<div style='color:#666; font-family:Courier New; padding:20px; text-align:center;'>// NO TRANSMISSIONS FOUND IN ARCHIVE //</div>")
            return

        html_parts = []
        for m in filtered:
            role = m.get("role", "User").upper()
            ts = m.get("timestamp", "")
            content = m.get("content", "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
            if role == "USER":
                badge_color = "#ffffff"
                bg_color = "rgba(255, 255, 255, 0.05)"
                border_color = "rgba(255, 255, 255, 0.2)"
                title = f"<b style='color:#00ff9d;'>[YOU]</b> <span style='color:#888; font-size:9px;'>{ts}</span>"
            else:
                badge_color = "#00f0ff"
                bg_color = "rgba(0, 240, 255, 0.05)"
                border_color = "rgba(0, 240, 255, 0.3)"
                title = f"<b style='color:#00f0ff;'>[SAM]</b> <span style='color:#888; font-size:9px;'>{ts}</span>"

            card = f"""
            <div style='background:{bg_color}; border-left:3px solid {border_color}; margin-bottom:8px; padding:6px 10px; border-radius:3px;'>
                <div style='margin-bottom:3px;'>{title}</div>
                <div style='color:{badge_color}; line-height:1.4;'>{content}</div>
            </div>
            """
            html_parts.append(card)

        self._viewer.setHtml("".join(html_parts))
        sb = self._viewer.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())

    def _copy_all(self):
        text = self._viewer.toPlainText()
        if text:
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(text)
                self._count_lbl.setText("COPIED TO CLIPBOARD!")
                QTimer.singleShot(2000, lambda: self._apply_filter(self._search_input.text()))

    def _clear_chats(self):
        reply = QMessageBox.question(
            self,
            "Confirm Archive Purge",
            "Are you sure you want to purge all stored conversation transcripts from memory?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            from memory.chat_history import clear_history
            clear_history()
            self._reload_chats()


# ── MacBook & Cross-Platform Zoom Event Filter ────────────────────────────────
class ZoomEventFilter(QObject):
    """
    Captures native MacBook trackpad gestures (pinch-to-zoom, smart-zoom),
    mouse wheel with Cmd/Ctrl modifier, and zoom keyboard shortcuts (Cmd+/Cmd-).
    """
    def __init__(self, window: MainWindow):
        super().__init__()
        self._window = window
        self._last_event_time = 0.0

    def eventFilter(self, obj, ev):
        try:
            ev_type = ev.type()

            # 1. Native Gestures (MacBook Trackpad pinch-to-zoom & double-tap)
            if ev_type == QEvent.Type.NativeGesture:
                g_type = ev.gestureType()
                if g_type == Qt.NativeGestureType.ZoomNativeGesture:
                    val = ev.value()
                    if abs(val) > 0.002:
                        self._window.zoom_by_delta(val * 0.75)
                        return True
                elif g_type == Qt.NativeGestureType.SmartZoomNativeGesture:
                    self._window.toggle_smart_zoom()
                    return True

            # 2. Wheel events with Cmd (Meta) or Ctrl
            elif ev_type == QEvent.Type.Wheel:
                mods = ev.modifiers()
                if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
                    delta = ev.angleDelta().y()
                    if delta != 0:
                        now = time.time()
                        if now - self._last_event_time > 0.04:
                            self._last_event_time = now
                            if delta > 0:
                                self._window.zoom_in()
                            else:
                                self._window.zoom_out()
                        return True

            # 3. Key press shortcuts with Cmd or Ctrl
            elif ev_type == QEvent.Type.KeyPress:
                mods = ev.modifiers()
                if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
                    k = ev.key()
                    t = ev.text()
                    # Zoom In: Cmd + = or Cmd + + or '+' / '='
                    if k in (Qt.Key.Key_Equal, Qt.Key.Key_Plus) or t in ("=", "+"):
                        self._window.zoom_in()
                        return True
                    # Zoom Out: Cmd + - or Cmd + _ or '-' / '_'
                    elif k in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore) or t in ("-", "_"):
                        self._window.zoom_out()
                        return True
                    # Reset Zoom: Cmd + 0 or '0'
                    elif k == Qt.Key.Key_0 or t == "0":
                        self._window.zoom_reset()
                        return True
        except Exception:
            pass

        return super().eventFilter(obj, ev)


# ── Main Application Window ───────────────────────────────────────────────────
class MainWindow(QMainWindow):
    _log_sig        = pyqtSignal(str)
    _state_sig      = pyqtSignal(str)
    _content_sig    = pyqtSignal(str, str)
    _mic_level_sig  = pyqtSignal(float)
    _wake_sig       = pyqtSignal(str)
    _task_sig       = pyqtSignal(str)
    _browser_sig    = pyqtSignal(str)
    _vscode_sig     = pyqtSignal(str)
    _queue_sig      = pyqtSignal(str)
    _mute_sig       = pyqtSignal(bool)
    _salutation_sig = pyqtSignal(str, str)

    def __init__(self, face_path: str):
        super().__init__()
        self._face_path = face_path

        # 1. Overlay pointers
        self._quick_drawer: QWidget | None = None
        self.on_text_command   = None
        self.on_interrupt      = None
        self.on_wake_trigger   = None
        self.on_clap_toggle    = None
        self._muted            = False
        self._chat_history_dialog = None

        # 2. Config & Theme
        _cfg = _read_full_config()
        self._clap_enabled: bool = bool(_cfg.get("clap_to_wake_enabled", True))
        self._assistant_name: str = (_cfg.get("assistant_name") or "SAM").strip()
        _display = self._assistant_name.upper()

        _ui_color = (_cfg.get("ui_color") or "").strip()
        if _ui_color and _ui_color.lower() != DEFAULT_UI_COLOR:
            apply_ui_accent(_ui_color)

        # 3. Dynamic Zoom Factor (persisted in config)
        _saved_zoom = _cfg.get("ui_zoom", 1.0)
        try:
            self._zoom_factor: float = float(_saved_zoom)
        except (ValueError, TypeError):
            self._zoom_factor = 1.0
        self._zoom_factor = max(0.70, min(2.40, self._zoom_factor))

        self.setWindowTitle(f"{_display} — MARK XLIX // CYBER CORE")
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move((screen.width() - _DEFAULT_W) // 2, (screen.height() - _DEFAULT_H) // 2)

        central = QWidget()
        central.setStyleSheet(f"background: {C.BG};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(8, 8, 8, 8)
        body.setSpacing(8)

        self._left_panel = self._build_left_panel()
        body.addWidget(self._left_panel, stretch=0)

        # Center Column: HUD Canvas & Content Splitter
        self.hud = HudCanvas(face_path, _display)
        self._content_panel = self._build_content_panel()

        self._center_split = QSplitter(Qt.Orientation.Vertical)
        self._center_split.setStyleSheet(f"""
            QSplitter::handle {{
                background: {C.BORDER}; height: 3px;
            }}
            QSplitter::handle:hover {{
                background: {C.CYAN};
            }}
        """)
        self._center_split.addWidget(self.hud)
        self._center_split.addWidget(self._content_panel)
        self._center_split.setStretchFactor(0, 4)
        self._center_split.setStretchFactor(1, 1)
        self._center_split.setCollapsible(0, False)
        body.addWidget(self._center_split, stretch=5)

        self._right_panel = self._build_right_panel()
        body.addWidget(self._right_panel, stretch=0)

        root.addLayout(body, stretch=1)
        root.addWidget(self._build_footer())

        # Drawer overlay
        self._quick_drawer = self._build_quick_drawer()

        # Timers
        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)
        self._tick_clock()

        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(1800)
        self._update_metrics()

        # Signals
        self._log_sig.connect(self._log.append_log)
        self._state_sig.connect(self._apply_state)
        self._content_sig.connect(self._show_content)
        self._mic_level_sig.connect(self._on_mic_level)
        self._wake_sig.connect(self._on_wake_state)
        self._task_sig.connect(self._on_current_task)
        self._browser_sig.connect(self._on_browser_status)
        self._vscode_sig.connect(self._on_vscode_status)
        self._queue_sig.connect(self._on_queue_add)
        self._mute_sig.connect(self.set_muted)
        self._salutation_sig.connect(self._on_salutation_change)

        # Shortcuts (supports F4/F5 and Option+F4/Option+F5 on Mac)
        QShortcut(QKeySequence("F4"), self).activated.connect(self._toggle_mute)
        QShortcut(QKeySequence("Alt+F4"), self).activated.connect(self._toggle_mute)
        QShortcut(QKeySequence("F5"), self).activated.connect(self._trigger_wake)
        QShortcut(QKeySequence("Alt+F5"), self).activated.connect(self._trigger_wake)
        QShortcut(QKeySequence("F11"), self).activated.connect(self._toggle_fullscreen)
        QShortcut(QKeySequence("Escape"), self).activated.connect(self._do_interrupt)

        # Zoom Shortcuts (Command + / Command - / Command 0 and cross-platform Ctrl)
        for seq_str in [
            "Ctrl+=", "Ctrl++", "Meta+=", "Meta++",
            "Ctrl+-", "Ctrl+_", "Meta+-", "Meta+_",
            "Ctrl+0", "Meta+0",
        ]:
            try:
                sc = QShortcut(QKeySequence(seq_str), self)
                sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
                if "-" in seq_str or "_" in seq_str:
                    sc.activated.connect(self.zoom_out)
                elif "0" in seq_str:
                    sc.activated.connect(self.zoom_reset)
                else:
                    sc.activated.connect(self.zoom_in)
            except Exception:
                pass

        # Global event filter for native gestures and Cmd+Wheel
        self._zoom_filter = ZoomEventFilter(self)
        app_inst = QApplication.instance()
        if app_inst:
            app_inst.installEventFilter(self._zoom_filter)

        self._zoom_log_timer = QTimer(self)
        self._zoom_log_timer.setSingleShot(True)
        self._zoom_log_timer.timeout.connect(self._log_zoom_change)

        self._apply_zoom()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, '_quick_drawer', None) and self._quick_drawer.isVisible():
            self._position_quick_drawer()

    def _build_header(self) -> QWidget:
        w = QWidget()
        self._header_widget = w
        w.setFixedHeight(54)
        w.setStyleSheet(f"background: {C.DARK}; border-bottom: 1px solid {C.BORDER_B};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(18, 0, 18, 0)

        self._drawer_btn = QPushButton("◈ CONTROLS")
        self._drawer_btn.setFixedHeight(28)
        self._drawer_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._drawer_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._drawer_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL2}; color: {C.CYAN};
                border: 1px solid {C.BORDER_A}; border-radius: 4px; padding: 0 10px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border-color: {C.CYAN}; }}
        """)
        self._drawer_btn.clicked.connect(self._toggle_drawer)
        lay.addWidget(self._drawer_btn)

        self._chats_btn = QPushButton("📜 CHATS")
        self._chats_btn.setFixedHeight(28)
        self._chats_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._chats_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._chats_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL2}; color: {C.WHITE};
                border: 1px solid {C.BORDER_A}; border-radius: 4px; padding: 0 10px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border-color: {C.CYAN}; color: {C.CYAN}; }}
        """)
        self._chats_btn.clicked.connect(self.show_chat_history)
        lay.addWidget(self._chats_btn)

        demo_btn = QPushButton("▶ SIMULATE HUD")
        demo_btn.setFixedHeight(28)
        demo_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        demo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        demo_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL2}; color: {C.ACC2};
                border: 1px solid {C.BORDER_A}; border-radius: 4px; padding: 0 10px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border-color: {C.ACC2}; }}
        """)
        demo_btn.clicked.connect(self._cycle_demo_state)
        self._demo_btn = demo_btn
        lay.addWidget(demo_btn)

        lay.addStretch()

        mid = QVBoxLayout()
        mid.setSpacing(1)
        _disp = self._assistant_name.upper()
        self._title_lbl = QLabel(f"// {_disp} — MARK XLIX //")
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_lbl.setFont(QFont("Courier New", 15, QFont.Weight.Bold))
        self._title_lbl.setStyleSheet(f"color: {C.WHITE}; letter-spacing: 2px;")
        mid.addWidget(self._title_lbl)

        self._sub_lbl = QLabel("AUTONOMOUS TACTICAL INTELLIGENCE MATRIX")
        self._sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub_lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._sub_lbl.setStyleSheet(f"color: {C.CYAN}; letter-spacing: 1px;")
        mid.addWidget(self._sub_lbl)
        lay.addLayout(mid)

        lay.addStretch()

        right_col = QVBoxLayout()
        right_col.setSpacing(1)
        self._clock_lbl = QLabel("00:00:00")
        self._clock_lbl.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
        self._clock_lbl.setStyleSheet(f"color: {C.CYAN};")
        self._clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._clock_lbl)

        self._date_lbl = QLabel("")
        self._date_lbl.setFont(QFont("Courier New", 7))
        self._date_lbl.setStyleSheet(f"color: {C.TEXT_DIM};")
        self._date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._date_lbl)
        lay.addLayout(right_col)
        return w

    def _cycle_demo_state(self):
        states = ["LISTENING", "THINKING", "PROCESSING", "SPEAKING", "MUTED"]
        cur = self.hud.state
        idx = (states.index(cur) + 1) % len(states) if cur in states else 0
        nxt = states[idx]
        self._apply_state(nxt)
        self._log.append_log(f"SYS: Simulation state -> {nxt}")

    def _tick_clock(self):
        self._clock_lbl.setText(time.strftime("%H:%M:%S"))
        self._date_lbl.setText(time.strftime("%a %d %b %Y").upper())

    def _build_left_panel(self) -> QWidget:
        panel = CyberPanel(tag="SYS_TELEMETRY")
        panel.setFixedWidth(_LEFT_W)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 24, 10, 12)
        lay.setSpacing(6)

        self._bar_cpu = SegmentedMetricBar("CPU LOAD", C.CYAN)
        self._bar_mem = SegmentedMetricBar("MEMORY",   C.PRI)
        self._bar_net = SegmentedMetricBar("NET I/O",  C.GREEN)
        self._bar_gpu = SegmentedMetricBar("GPU CORE", C.ACC)
        self._bar_tmp = SegmentedMetricBar("THERMAL",  "#ff0055")
        self._bar_mic = SegmentedMetricBar("MIC GAIN", C.CYAN)

        self._metric_bars = [
            self._bar_cpu, self._bar_mem, self._bar_net,
            self._bar_gpu, self._bar_tmp, self._bar_mic
        ]
        for bar in self._metric_bars:
            lay.addWidget(bar)

        lay.addSpacing(6)

        info_box = QWidget()
        info_box.setStyleSheet(f"background: {C.PANEL2}; border: 1px solid {C.BORDER}; border-radius: 4px;")
        ib_lay = QVBoxLayout(info_box)
        ib_lay.setContentsMargins(6, 6, 6, 6)
        ib_lay.setSpacing(3)

        self._uptime_lbl = QLabel("UP  --:--")
        self._uptime_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._uptime_lbl.setStyleSheet(f"color: {C.GREEN}; border: none;")
        ib_lay.addWidget(self._uptime_lbl)

        self._proc_lbl = QLabel("PROC  --")
        self._proc_lbl.setFont(QFont("Courier New", 8))
        self._proc_lbl.setStyleSheet(f"color: {C.TEXT_MED}; border: none;")
        ib_lay.addWidget(self._proc_lbl)
        lay.addWidget(info_box)

        lay.addStretch()

        self._badge_wake    = QLabel("WAKE\n● HOT MIC")
        self._badge_task    = QLabel("TASK\nIDLE")
        self._badge_browser = QLabel("BROWSER\nSTANDBY")
        self._badge_vscode  = QLabel("DEV CORE\nSTANDBY")

        for lbl, col in [
            (self._badge_wake,    C.GREEN),
            (self._badge_task,    C.CYAN),
            (self._badge_browser, C.TEXT_DIM),
            (self._badge_vscode,  C.TEXT_DIM),
        ]:
            lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f"""
                color: {col}; background: {C.PANEL2};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px;
            """)
            lay.addWidget(lbl)

        return panel

    def _build_right_panel(self) -> QWidget:
        panel = CyberPanel(tag="COMMAND_MATRIX")
        panel.setFixedWidth(_RIGHT_W)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 24, 10, 12)
        lay.setSpacing(6)

        self._log = LogWidget()
        lay.addWidget(self._log, stretch=1)

        self._queue_log = QTextEdit()
        self._queue_log.setReadOnly(True)
        self._queue_log.setFont(QFont("Courier New", 7))
        self._queue_log.setFixedHeight(64)
        self._queue_log.setStyleSheet(f"""
            QTextEdit {{
                background: {C.DARK}; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 4px; padding: 4px;
            }}
        """)
        self._queue_log.setPlaceholderText("// NO QUEUED PROTOCOLS //")
        lay.addWidget(self._queue_log)

        self._drop_zone = FileDropZone()
        self._drop_zone.file_selected.connect(lambda p: self._log.append_log(f"FILE: Loaded {Path(p).name}"))
        lay.addWidget(self._drop_zone)

        lay.addLayout(self._build_input_row())

        self._interrupt_btn = QPushButton("✋  EMERGENCY INTERRUPT  [ESC]")
        self._interrupt_btn.setFixedHeight(32)
        self._interrupt_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._interrupt_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._interrupt_btn.setStyleSheet(f"""
            QPushButton {{
                background: #20000a; color: {C.MUTED_C};
                border: 1px solid {C.MUTED_C}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: #400014; border-color: {C.WHITE}; }}
        """)
        self._interrupt_btn.clicked.connect(self._do_interrupt)
        lay.addWidget(self._interrupt_btn)

        self._mute_btn = QPushButton("🎙  MICROPHONE ACTIVE")
        self._mute_btn.setFixedHeight(30)
        self._mute_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._toggle_mute)
        self._style_mute_btn()
        lay.addWidget(self._mute_btn)

        self._camera_btn = QPushButton("📷  CAMERA / VIDEO")
        self._camera_btn.setFixedHeight(30)
        self._camera_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._camera_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._camera_btn.setStyleSheet(f"background:{C.PANEL2}; color:{C.CYAN}; border:1px solid {C.BORDER}; border-radius:3px;")
        self._camera_btn.clicked.connect(self._open_camera)
        lay.addWidget(self._camera_btn)

        self._voice_record_btn = QPushButton("🎙  VOICE-ONLY RECORDING")
        self._voice_record_btn.setFixedHeight(30)
        self._voice_record_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._voice_record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._voice_record_btn.setStyleSheet(f"background:{C.PANEL2}; color:{C.CYAN}; border:1px solid {C.BORDER}; border-radius:3px;")
        self._voice_record_btn.clicked.connect(self._open_voice_recorder)
        lay.addWidget(self._voice_record_btn)

        return panel

    def _open_camera(self):
        try:
            dialog = CameraCaptureDialog(self)
            dialog.exec()
        except Exception as exc:
            QMessageBox.warning(self, "Camera unavailable", f"Could not open the camera: {exc}")

    def _open_voice_recorder(self):
        dialog = VoiceOnlyRecorderDialog(self)
        dialog.exec()

    def _build_input_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(5)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Enter command or query protocol…")
        self._input.setFont(QFont("Courier New", 9))
        self._input.setFixedHeight(32)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: #080014; color: {C.WHITE};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.CYAN}; }}
        """)
        self._input.returnPressed.connect(self._send)
        row.addWidget(self._input)

        send = QPushButton("▸")
        send.setFixedSize(32, 32)
        send.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL2}; color: {C.CYAN};
                border: 1px solid {C.CYAN}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border-color: {C.WHITE}; }}
        """)
        send.clicked.connect(self._send)
        self._send_btn = send
        row.addWidget(send)
        return row

    def _build_content_panel(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(f"background: {C.PANEL}; border-top: 1px solid {C.BORDER_B};")
        w.hide()

        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(4)

        hdr = QHBoxLayout()
        self._content_title_lbl = QLabel("BRIEFING")
        self._content_title_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._content_title_lbl.setStyleSheet(f"color: {C.CYAN}; letter-spacing: 1px;")
        hdr.addWidget(self._content_title_lbl)
        hdr.addStretch()

        dismiss = QPushButton("DISMISS  ✕")
        dismiss.setFont(QFont("Courier New", 7))
        dismiss.setFixedHeight(18)
        dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        dismiss.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 2px; padding: 0 4px;
            }}
            QPushButton:hover {{ color: {C.WHITE}; border-color: {C.CYAN}; }}
        """)
        dismiss.clicked.connect(w.hide)
        self._content_dismiss_btn = dismiss
        hdr.addWidget(dismiss)
        lay.addLayout(hdr)

        self._content_display = QTextEdit()
        self._content_display.setReadOnly(True)
        self._content_display.setFont(QFont("Courier New", 8))
        self._content_display.setStyleSheet(f"""
            QTextEdit {{
                background: {C.DARK}; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 6px;
            }}
        """)
        lay.addWidget(self._content_display)
        return w

    def _show_content(self, title: str, text: str):
        self._content_title_lbl.setText(f"// {title.upper()[:40]} //")
        self._content_display.setPlainText(text)
        self._content_panel.show()
        total = self._center_split.height()
        self._center_split.setSizes([max(total - 220, 120), 220])

    def _build_quick_drawer(self) -> QWidget:
        w = QWidget(self.centralWidget())
        w.setStyleSheet(f"""
            QWidget {{
                background: rgba(8, 0, 18, 252);
                border: 1px solid {C.CYAN};
                border-radius: 6px;
            }}
        """)
        w.hide()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(6)

        hdr = QLabel("// TACTICAL THEME PRESETS //")
        hdr.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.CYAN}; background: transparent;")
        lay.addWidget(hdr)

        address_label = QLabel("WHAT SHOULD SAM CALL YOU?")
        address_label.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        address_label.setStyleSheet(f"color: {C.CYAN}; background: transparent; border: 0;")
        lay.addWidget(address_label)
        self._address_choice = QComboBox()
        self._address_choice.addItems(["Ma'am", "Sir", "Other"])
        saved_prefs = _read_full_config()
        saved_address = saved_prefs.get("salutation", "Sir")
        self._address_choice.setCurrentText(saved_address if saved_address in ("Ma'am", "Sir", "Other") else "Sir")
        self._address_choice.setStyleSheet(f"color: {C.WHITE}; background: {C.PANEL2}; border: 1px solid {C.BORDER}; padding: 4px;")
        lay.addWidget(self._address_choice)
        self._address_custom = QLineEdit(str(saved_prefs.get("other_name", "")))
        self._address_custom.setPlaceholderText("Enter the name to use")
        self._address_custom.setMaxLength(80)
        self._address_custom.setStyleSheet(f"color: {C.WHITE}; background: {C.PANEL2}; border: 1px solid {C.BORDER}; padding: 4px;")
        self._address_custom.setVisible(self._address_choice.currentText() == "Other")
        lay.addWidget(self._address_custom)
        self._address_choice.currentTextChanged.connect(self._address_choice_changed)
        self._address_custom.textChanged.connect(lambda _text: self._save_address_preference())

        # 5 Instant Sci-Fi Presets
        presets = [
            ("🟡 STARK GOLD",    "#ffaa00"),
            ("🔵 TACTICAL CYAN",  "#00f0ff"),
            ("🟢 NEURAL MATRIX",  "#00ff9d"),
            ("🔴 COMBAT MODE",    "#ff0055"),
            ("🟣 NEO VIOLET",     "#a855f7"),
        ]

        for label, hex_col in presets:
            btn = QPushButton(label)
            btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            btn.setFixedHeight(26)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {C.PANEL2}; color: {hex_col};
                    border: 1px solid {hex_col}; border-radius: 3px;
                    text-align: left; padding: 0 8px;
                }}
                QPushButton:hover {{ background: {C.PRI_GHO}; color: {C.WHITE}; }}
            """)
            btn.clicked.connect(lambda _, h=hex_col: self._apply_theme_preset(h))
            lay.addWidget(btn)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER};"); lay.addWidget(sep2)

        zoom_hdr = QLabel("// INTERFACE ZOOM //")
        zoom_hdr.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        zoom_hdr.setStyleSheet(f"color: {C.CYAN}; background: transparent; border: 0;")
        lay.addWidget(zoom_hdr)

        zoom_row = QHBoxLayout()
        zoom_row.setSpacing(6)

        self._drawer_zoom_out_btn = QPushButton("－ ZOOM OUT")
        self._drawer_zoom_out_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._drawer_zoom_out_btn.setFixedHeight(26)
        self._drawer_zoom_out_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._drawer_zoom_out_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL2}; color: {C.WHITE};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 0 6px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; color: {C.CYAN}; border-color: {C.CYAN}; }}
        """)
        self._drawer_zoom_out_btn.clicked.connect(self.zoom_out)

        pct = int(round(self._zoom_factor * 100))
        self._drawer_zoom_lbl = QLabel(f"{pct}%")
        self._drawer_zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drawer_zoom_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._drawer_zoom_lbl.setStyleSheet(f"color: {C.CYAN}; background: transparent; border: 0;")

        self._drawer_zoom_in_btn = QPushButton("＋ ZOOM IN")
        self._drawer_zoom_in_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._drawer_zoom_in_btn.setFixedHeight(26)
        self._drawer_zoom_in_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._drawer_zoom_in_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL2}; color: {C.WHITE};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 0 6px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; color: {C.CYAN}; border-color: {C.CYAN}; }}
        """)
        self._drawer_zoom_in_btn.clicked.connect(self.zoom_in)

        zoom_row.addWidget(self._drawer_zoom_out_btn)
        zoom_row.addWidget(self._drawer_zoom_lbl)
        zoom_row.addWidget(self._drawer_zoom_in_btn)
        lay.addLayout(zoom_row)

        self._drawer_zoom_reset_btn = QPushButton("↺  RESET ZOOM  [⌘0]")
        self._drawer_zoom_reset_btn.setFont(QFont("Courier New", 8))
        self._drawer_zoom_reset_btn.setFixedHeight(26)
        self._drawer_zoom_reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._drawer_zoom_reset_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL2}; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
                text-align: left; padding: 0 8px;
            }}
            QPushButton:hover {{ color: {C.WHITE}; border-color: {C.CYAN}; }}
        """)
        self._drawer_zoom_reset_btn.clicked.connect(self.zoom_reset)
        lay.addWidget(self._drawer_zoom_reset_btn)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); lay.addWidget(sep)

        fs_btn = QPushButton("⛶  TOGGLE FULLSCREEN  [F11]")
        fs_btn.setFont(QFont("Courier New", 8))
        fs_btn.setFixedHeight(26)
        fs_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL2}; color: {C.WHITE};
                border: 1px solid {C.BORDER}; border-radius: 3px;
                text-align: left; padding: 0 8px;
            }}
            QPushButton:hover {{ color: {C.CYAN}; border-color: {C.CYAN}; }}
        """)
        fs_btn.clicked.connect(self._toggle_fullscreen)
        lay.addWidget(fs_btn)

        sep_wake = QFrame(); sep_wake.setFrameShape(QFrame.Shape.HLine)
        sep_wake.setStyleSheet(f"color: {C.BORDER};"); lay.addWidget(sep_wake)

        wake_hdr = QLabel("// WAKE SENSORS & ARCHIVE //")
        wake_hdr.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        wake_hdr.setStyleSheet(f"color: {C.CYAN}; background: transparent; border: 0;")
        lay.addWidget(wake_hdr)

        self._clap_toggle_btn = QPushButton()
        self._clap_toggle_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._clap_toggle_btn.setFixedHeight(28)
        self._clap_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_clap_btn_style()
        self._clap_toggle_btn.clicked.connect(self._toggle_clap_wake)
        lay.addWidget(self._clap_toggle_btn)

        chats_drawer_btn = QPushButton("📜 PREVIOUS CHATS ARCHIVE")
        chats_drawer_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        chats_drawer_btn.setFixedHeight(28)
        chats_drawer_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        chats_drawer_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL2}; color: {C.CYAN};
                border: 1px solid {C.BORDER_A}; border-radius: 3px;
                text-align: left; padding: 0 8px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; color: {C.WHITE}; border-color: {C.CYAN}; }}
        """)
        chats_drawer_btn.clicked.connect(self.show_chat_history)
        lay.addWidget(chats_drawer_btn)

        return w

    def _address_choice_changed(self, choice: str):
        self._address_custom.setVisible(choice == "Other")
        self._save_address_preference()

    def _save_address_preference(self):
        try:
            config = _read_full_config()
            sal = self._address_choice.currentText()
            other = self._address_custom.text().strip()[:80]
            config["salutation"] = sal
            config["other_name"] = other
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            temp_file = API_FILE.with_suffix(".tmp")
            temp_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
            temp_file.replace(API_FILE)
            addr = (other if other else "friend") if sal == "Other" else sal
            self._log.append_log(f"SYS: Salutation instantaneously updated to '{addr}'.")
        except Exception as exc:
            self._log.append_log(f"SYS: Could not save address preference: {exc}")

    def _on_salutation_change(self, salutation: str, other_name: str):
        if salutation in ("Sir", "Ma'am", "Other"):
            self._address_choice.blockSignals(True)
            self._address_choice.setCurrentText(salutation)
            self._address_choice.blockSignals(False)
            self._address_custom.setVisible(salutation == "Other")
        if other_name:
            self._address_custom.blockSignals(True)
            self._address_custom.setText(other_name)
            self._address_custom.blockSignals(False)
        self._save_address_preference()

    def form_of_address(self) -> str:
        try:
            choice = self._address_choice.currentText()
            if choice == "Other":
                custom = self._address_custom.text().strip()
                return custom if custom else "friend"
            return choice if choice in ("Sir", "Ma'am") else "Sir"
        except Exception:
            from core.llm_client import get_salutation
            return get_salutation()

    def _update_clap_btn_style(self):
        col = C.GREEN if getattr(self, "_clap_enabled", True) else C.TEXT_DIM
        status_txt = "ACTIVE" if getattr(self, "_clap_enabled", True) else "MUTED"
        if hasattr(self, "_clap_toggle_btn") and self._clap_toggle_btn:
            self._clap_toggle_btn.setText(f"👏 CLAP TO WAKE: {status_txt}")
            self._clap_toggle_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {C.PANEL2}; color: {col};
                    border: 1px solid {col}; border-radius: 3px;
                    text-align: left; padding: 0 8px;
                }}
                QPushButton:hover {{ background: {C.PRI_GHO}; color: {C.WHITE}; }}
            """)

    def _toggle_clap_wake(self):
        self._clap_enabled = not getattr(self, "_clap_enabled", True)
        self._update_clap_btn_style()
        try:
            config = _read_full_config()
            config["clap_to_wake_enabled"] = self._clap_enabled
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            temp_file = API_FILE.with_suffix(".tmp")
            temp_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
            temp_file.replace(API_FILE)
            state_str = "ACTIVATED" if self._clap_enabled else "MUTED"
            self._log.append_log(f"SYS: Clap-to-wake sensor {state_str}.")
        except Exception as exc:
            self._log.append_log(f"SYS: Could not save clap preference: {exc}")
        if hasattr(self, "on_clap_toggle") and callable(self.on_clap_toggle):
            self.on_clap_toggle(self._clap_enabled)

    def show_chat_history(self):
        if not hasattr(self, "_chat_history_dialog") or self._chat_history_dialog is None:
            self._chat_history_dialog = ChatHistoryDialog(self)
        else:
            self._chat_history_dialog._reload_chats()
        self._chat_history_dialog.show()
        self._chat_history_dialog.raise_()
        self._chat_history_dialog.activateWindow()

    def _apply_theme_preset(self, hex_color: str):
        old = current_palette()
        if apply_ui_accent(hex_color):
            retheme_all_widgets(old, current_palette())
            self._log.append_log(f"SYS: Theme shifted to {hex_color.upper()}")

    def _toggle_drawer(self):
        if getattr(self, '_quick_drawer', None):
            if self._quick_drawer.isVisible():
                self._quick_drawer.hide()
            else:
                self._position_quick_drawer()
                self._quick_drawer.show()
                self._quick_drawer.raise_()

    def _position_quick_drawer(self):
        if hasattr(self, '_quick_drawer') and self._quick_drawer:
            dw = max(240, int(round(240 * min(1.25, self._zoom_factor))))
            self._quick_drawer.setFixedWidth(dw)
            self._quick_drawer.adjustSize()
            top = (self._header_widget.height() + 2) if hasattr(self, "_header_widget") else 56
            self._quick_drawer.setGeometry(18, top, dw, self._quick_drawer.sizeHint().height())

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(22)
        w.setStyleSheet(f"background: {C.DARK}; border-top: 1px solid {C.BORDER};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(14, 0, 14, 0)
        pct = int(round(self._zoom_factor * 100))
        lbl = QLabel(f"[F4] Mute Audio  ·  [F11] Fullscreen  ·  [⌘+/⌘-] Zoom ({pct}%)  ·  [ESC] Interrupt  ·  [CLICK HUD] Reticle")
        lbl.setFont(QFont("Courier New", 7))
        lbl.setStyleSheet(f"color: {C.TEXT_DIM};")
        self._footer_lbl = lbl
        lay.addWidget(lbl)
        lay.addStretch()
        tag = QLabel("MARK XLIX // CYBERNETIC MATRIX")
        tag.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        tag.setStyleSheet(f"color: {C.CYAN};")
        self._footer_tag = tag
        lay.addWidget(tag)
        self._footer_widget = w
        return w

    # ── Dynamic Font & UI Zoom Controls ──────────────────────────────────────────
    def zoom_in(self):
        self.set_zoom_factor(self._zoom_factor + 0.10)

    def zoom_out(self):
        self.set_zoom_factor(self._zoom_factor - 0.10)

    def zoom_reset(self):
        self.set_zoom_factor(1.0)

    def zoom_by_delta(self, delta: float):
        self.set_zoom_factor(self._zoom_factor + delta)

    def toggle_smart_zoom(self):
        if abs(self._zoom_factor - 1.0) < 0.05:
            self.set_zoom_factor(1.30)
        else:
            self.set_zoom_factor(1.0)

    def set_zoom_factor(self, factor: float):
        factor = max(0.70, min(2.40, round(factor, 2)))
        if abs(factor - self._zoom_factor) < 0.005:
            return
        self._zoom_factor = factor
        self._apply_zoom()
        pct = int(round(self._zoom_factor * 100))
        if hasattr(self, "hud"):
            self.hud.show_zoom_indicator(f"ZOOM // {pct}%")
        self._save_zoom_preference()
        if hasattr(self, "_zoom_log_timer"):
            self._zoom_log_timer.start(450)

    def _log_zoom_change(self):
        pct = int(round(self._zoom_factor * 100))
        pt = max(6, int(round(9 * self._zoom_factor)))
        self._log.append_log(f"SYS: Interface zoom scaled to {pct}% (Font size: {pt}pt)")

    def _save_zoom_preference(self):
        try:
            config = _read_full_config()
            config["ui_zoom"] = round(self._zoom_factor, 2)
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            temp_file = API_FILE.with_suffix(".tmp")
            temp_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
            temp_file.replace(API_FILE)
        except Exception:
            pass

    def _apply_zoom(self):
        factor = self._zoom_factor
        def _f(pt: int, bold: bool = False) -> QFont:
            size = max(6, int(round(pt * factor)))
            return QFont("Courier New", size, QFont.Weight.Bold if bold else QFont.Weight.Normal)

        # 1. Main activity log terminal
        if hasattr(self, "_log"):
            if hasattr(self._log, "set_zoom_factor"):
                self._log.set_zoom_factor(factor)
            else:
                f = _f(9)
                self._log.setFont(f)
                self._log.document().setDefaultFont(f)

        # 2. Queue log
        if hasattr(self, "_queue_log"):
            q_font = _f(7)
            self._queue_log.setFont(q_font)
            self._queue_log.document().setDefaultFont(q_font)
            self._queue_log.setFixedHeight(max(54, int(round(64 * min(1.35, factor)))))

        # 3. Content briefing panel
        if hasattr(self, "_content_display"):
            c_font = _f(8)
            self._content_display.setFont(c_font)
            self._content_display.document().setDefaultFont(c_font)
        if hasattr(self, "_content_title_lbl"):
            self._content_title_lbl.setFont(_f(8, True))
        if hasattr(self, "_content_dismiss_btn"):
            self._content_dismiss_btn.setFont(_f(7))

        # 4. Command Input Row
        if hasattr(self, "_input"):
            self._input.setFont(_f(9))
            self._input.setFixedHeight(max(32, int(round(32 * min(1.3, factor)))))
        if hasattr(self, "_send_btn"):
            self._send_btn.setFont(_f(12, True))
            h = self._input.height() if hasattr(self, "_input") else 32
            self._send_btn.setFixedSize(h, h)

        # 5. Right panel action buttons
        for btn, base_h in [
            (getattr(self, "_interrupt_btn", None), 32),
            (getattr(self, "_mute_btn", None), 30),
            (getattr(self, "_camera_btn", None), 30),
            (getattr(self, "_voice_record_btn", None), 30),
        ]:
            if btn:
                btn.setFont(_f(8, True))
                btn.setFixedHeight(max(base_h, int(round(base_h * min(1.25, factor)))))

        # 6. Header
        if hasattr(self, "_header_widget"):
            self._header_widget.setFixedHeight(max(50, int(round(54 * min(1.25, factor)))))
        if hasattr(self, "_drawer_btn"):
            self._drawer_btn.setFont(_f(8, True))
        if hasattr(self, "_demo_btn"):
            self._demo_btn.setFont(_f(8, True))
        if hasattr(self, "_title_lbl"):
            self._title_lbl.setFont(_f(15, True))
        if hasattr(self, "_sub_lbl"):
            self._sub_lbl.setFont(_f(7, True))
        if hasattr(self, "_clock_lbl"):
            self._clock_lbl.setFont(_f(13, True))
        if hasattr(self, "_date_lbl"):
            self._date_lbl.setFont(_f(7))

        # 7. Left Panel & Badges
        if hasattr(self, "_uptime_lbl"):
            self._uptime_lbl.setFont(_f(8, True))
        if hasattr(self, "_proc_lbl"):
            self._proc_lbl.setFont(_f(8))
        for badge in [
            getattr(self, "_badge_wake", None),
            getattr(self, "_badge_task", None),
            getattr(self, "_badge_browser", None),
            getattr(self, "_badge_vscode", None),
        ]:
            if badge:
                badge.setFont(_f(7, True))

        # 8. Custom components
        for bar in getattr(self, "_metric_bars", []):
            if hasattr(bar, "set_zoom_factor"):
                bar.set_zoom_factor(factor)

        if hasattr(self, "_drop_zone") and hasattr(self._drop_zone, "set_zoom_factor"):
            self._drop_zone.set_zoom_factor(factor)

        if hasattr(self, "hud") and hasattr(self.hud, "set_zoom_factor"):
            self.hud.set_zoom_factor(factor)

        if hasattr(self, "_left_panel") and hasattr(self._left_panel, "set_zoom_factor"):
            self._left_panel.set_zoom_factor(factor)
        if hasattr(self, "_right_panel") and hasattr(self._right_panel, "set_zoom_factor"):
            self._right_panel.set_zoom_factor(factor)

        # Scale panel widths gracefully
        if hasattr(self, "_left_panel"):
            self._left_panel.setFixedWidth(max(_LEFT_W, int(round(_LEFT_W * (1.0 + (factor - 1.0) * 0.25)))))
        if hasattr(self, "_right_panel"):
            self._right_panel.setFixedWidth(max(_RIGHT_W, int(round(_RIGHT_W * (1.0 + (factor - 1.0) * 0.25)))))

        # 9. Footer
        pct = int(round(factor * 100))
        if hasattr(self, "_footer_lbl"):
            self._footer_lbl.setFont(_f(7))
            self._footer_lbl.setText(f"[F4] Mute Audio  ·  [F11] Fullscreen  ·  [⌘+/⌘-] Zoom ({pct}%)  ·  [ESC] Interrupt  ·  [CLICK HUD] Target")
        if hasattr(self, "_footer_tag"):
            self._footer_tag.setFont(_f(7, True))
        if hasattr(self, "_footer_widget"):
            self._footer_widget.setFixedHeight(max(22, int(round(22 * min(1.25, factor)))))

        # 10. Quick drawer zoom controls
        if hasattr(self, "_drawer_zoom_lbl"):
            self._drawer_zoom_lbl.setText(f"{pct}%")
            self._drawer_zoom_lbl.setFont(_f(8, True))
        if hasattr(self, "_drawer_zoom_in_btn"):
            self._drawer_zoom_in_btn.setFont(_f(8, True))
        if hasattr(self, "_drawer_zoom_out_btn"):
            self._drawer_zoom_out_btn.setFont(_f(8, True))
        if hasattr(self, "_drawer_zoom_reset_btn"):
            self._drawer_zoom_reset_btn.setFont(_f(8))
        if hasattr(self, "_position_quick_drawer") and getattr(self, "_quick_drawer", None) and self._quick_drawer.isVisible():
            self._position_quick_drawer()

    def _update_metrics(self):
        snap = _metrics.snapshot()
        self._bar_cpu.set_value(snap["cpu"], f"{snap['cpu']:.0f}%")
        self._bar_mem.set_value(snap["mem"], f"{snap['mem']:.0f}%")

        net = snap["net"]
        net_str = f"{net*1024:.0f}KB/s" if net < 1.0 else f"{net:.1f}MB/s"
        self._bar_net.set_value(min(100, net * 10), net_str)

        try:
            boot_t  = psutil.boot_time()
            elapsed = time.time() - boot_t
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            self._uptime_lbl.setText(f"UP  {h:02d}:{m:02d}")
        except Exception:
            pass

        try:
            self._proc_lbl.setText(f"PROC  {len(psutil.pids())}")
        except Exception:
            pass

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _toggle_mute(self):
        self.set_muted(not self._muted)

    def set_muted(self, muted: bool):
        if self._muted == muted:
            return
        self._muted = muted
        self.hud.muted = self._muted
        self._style_mute_btn()
        
        if getattr(self, "on_mic_toggle", None):
            self.on_mic_toggle(self._muted)
            
        if self._muted:
            self._apply_state("MUTED")
            self._log.append_log("SYS: Microphone severed.")
        else:
            self._apply_state("LISTENING")
            self._log.append_log("SYS: Microphone online.")

    def _style_mute_btn(self):
        if self._muted:
            self._mute_btn.setText("🔇  MICROPHONE MUTED")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #20000a; color: {C.MUTED_C};
                    border: 1px solid {C.MUTED_C}; border-radius: 3px;
                }}
            """)
        else:
            self._mute_btn.setText("🎙  MICROPHONE ACTIVE")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #001a10; color: {C.GREEN};
                    border: 1px solid {C.GREEN}; border-radius: 3px;
                }}
                QPushButton:hover {{ background: #002e1c; }}
            """)

    def _send(self):
        txt = self._input.text().strip()
        if not txt:
            if self._drop_zone.current_files():
                txt = "Analyze the attached file(s) and explain what is in them."
            else:
                return
        self._input.clear()
        self._log.append_log(f"You: {txt}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,), daemon=True).start()

    def _do_interrupt(self):
        if self.on_interrupt:
            self.on_interrupt()
        self._log.append_log("SYS: Execution interrupted.")

    def _trigger_wake(self):
        if self._muted:
            self.set_muted(False)
        if getattr(self, "on_wake_trigger", None):
            self.on_wake_trigger()

    def _apply_state(self, state: str):
        self.hud.state = state
        self.hud.speaking = (state == "SPEAKING")

    def _on_mic_level(self, level: float):
        pct = max(0.0, min(100.0, level * 100))
        self._bar_mic.set_value(pct, f"{int(pct)}%")

    def _on_wake_state(self, state: str):
        lbl = "● LISTENING" if state == "LISTENING" else ("○ SLEEPING" if state == "SLEEPING" else "— HOT MIC —")
        col = C.GREEN if state in ("LISTENING", "OFF") else C.TEXT_DIM
        self._badge_wake.setText(f"WAKE\n{lbl}")
        self._badge_wake.setStyleSheet(f"color: {col}; background: {C.PANEL2}; border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px;")

    def _on_current_task(self, task: str):
        self._badge_task.setText(f"TASK\n{task[:14]}" if task else "TASK\nIDLE")
        col = C.CYAN if task else C.TEXT_DIM
        self._badge_task.setStyleSheet(f"color: {col}; background: {C.PANEL2}; border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px;")

    def _on_browser_status(self, status: str):
        active = status.upper() not in ("", "IDLE", "STANDBY")
        self._badge_browser.setText(f"BROWSER\n{status or 'STANDBY'}"[:20])
        col = C.CYAN if active else C.TEXT_DIM
        self._badge_browser.setStyleSheet(f"color: {col}; background: {C.PANEL2}; border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px;")

    def _on_vscode_status(self, status: str):
        active = status.upper() not in ("", "IDLE", "STANDBY")
        self._badge_vscode.setText(f"DEV CORE\n{status or 'STANDBY'}"[:20])
        col = C.CYAN if active else C.TEXT_DIM
        self._badge_vscode.setStyleSheet(f"color: {col}; background: {C.PANEL2}; border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px;")

    def _on_queue_add(self, line: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self._queue_log.append(f'<span style="color:{C.CYAN}">[{ts}]</span> {line}')


# ── Public API Wrapper ────────────────────────────────────────────────────────
class SamUI:
    def __init__(self, face_path: str = "", size=None):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        self._win = MainWindow(face_path)
        self._win.show()
        self._win.raise_()
        self._win.activateWindow()

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    def set_mic_level(self, level: float):
        self._win._mic_level_sig.emit(level)

    def set_wake_state(self, state: str):
        self._win._wake_sig.emit(state)

    def set_muted(self, muted: bool):
        self._win._mute_sig.emit(muted)

    def set_current_task(self, task: str):
        self._win._task_sig.emit(task)

    def set_browser_status(self, status: str):
        self._win._browser_sig.emit(status)

    def set_vscode_status(self, status: str):
        self._win._vscode_sig.emit(status)

    def selected_file_paths(self) -> list[str]:
        """Return all paths currently selected in the desktop attachment area."""
        return self._win._drop_zone.current_files()

    def form_of_address(self) -> str:
        return self._win.form_of_address()

    def set_salutation(self, salutation: str, other_name: str = "") -> str:
        try:
            from core.llm_client import set_salutation as persist_salutation
            addr = persist_salutation(salutation, other_name)
        except Exception:
            addr = other_name if (salutation == "Other" and other_name) else salutation
        self._win._salutation_sig.emit(salutation, other_name)
        return addr

    def queue_add(self, line: str):
        self._win._queue_sig.emit(line)

    def show_content(self, title: str, text: str):
        self._win._content_sig.emit(title, text)

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, fn):
        self._win.on_text_command = fn

    @property
    def on_interrupt(self):
        return self._win.on_interrupt

    @on_interrupt.setter
    def on_interrupt(self, fn):
        self._win.on_interrupt = fn

    @property
    def on_mic_toggle(self):
        return getattr(self._win, "on_mic_toggle", None)

    @on_mic_toggle.setter
    def on_mic_toggle(self, fn):
        self._win.on_mic_toggle = fn

    @property
    def on_wake_trigger(self):
        return getattr(self._win, "on_wake_trigger", None)

    @on_wake_trigger.setter
    def on_wake_trigger(self, fn):
        self._win.on_wake_trigger = fn

    def run(self):
        self._app.exec()


if __name__ == "__main__":
    ui = SamUI()
    ui.write_log("SYS: Quantum neural matrix initialized.")
    ui.write_log("SYS: MARK XLIX online. All telemetry nominal.")
    ui.run()
