import os
import re
import sys
import json
import threading
import tempfile
import subprocess
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from tkinter import filedialog, messagebox, font as tkfont
import customtkinter as ctk
from PIL import Image, ImageDraw, ImageOps, ImageSequence, ImageTk
import imageio_ffmpeg

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _HAS_DND = True
except Exception:
    _HAS_DND = False

APP_VERSION = "2.3.0"

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def _settings_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config"))
    d = os.path.join(base, "WebPConverter")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return os.path.abspath(".")
    return d


SETTINGS_FILE = os.path.join(_settings_dir(), "settings.json")

MAX_DIMENSION = 7680
MAX_PREVIEW_FRAMES = 200

VALID_FORMATS = (".mp4", ".mkv", ".webm", ".gif")
VALID_RESOLUTIONS = ("Same Resolution", "480p", "720p", "1080p", "4K", "Custom")
VALID_THEMES = ("dark", "light")

RESOLUTION_MAP = {
    "480p":  (854,  480),
    "720p":  (1280, 720),
    "1080p": (1920, 1080),
    "4K":    (3840, 2160),
}

# Lossless ffmpeg arguments per container, each verified bit-exact by decoding
# the output back. Compressed output's yuv420p can't be used here: 4:2:0 chroma
# subsampling discards colour even at qp 0, so lossless changes pixel format,
# not just the quality knob.
LOSSLESS_ARGS = {
    ".mp4":  ["-c:v", "libx264rgb", "-qp", "0", "-pix_fmt", "rgb24",
              "-preset", "medium"],
    ".mkv":  ["-c:v", "ffv1", "-level", "3", "-pix_fmt", "rgb32"],   # keeps alpha
    ".webm": ["-c:v", "libvpx-vp9", "-lossless", "1", "-pix_fmt", "gbrp",
              "-row-mt", "1", "-deadline", "good", "-cpu-used", "2"],
}


def encoder_args(fmt: str, crf: int, lossless: bool) -> list:
    """ffmpeg video arguments for a container."""
    if lossless:
        args = list(LOSSLESS_ARGS[fmt])
    elif fmt == ".webm":
        args = ["-c:v", "libvpx-vp9", "-crf", str(crf), "-b:v", "0",
                "-row-mt", "1", "-deadline", "good", "-cpu-used", "2",
                "-pix_fmt", "yuv420p"]
    else:
        args = ["-c:v", "libx264", "-crf", str(crf), "-pix_fmt", "yuv420p",
                "-preset", "medium"]
    if fmt == ".mp4":
        args += ["-movflags", "+faststart"]
    return args


def keeps_alpha(fmt: str, lossless: bool) -> bool:
    """Only lossless MKV (FFV1 rgb32) carries an alpha channel."""
    return lossless and fmt == ".mkv"


CODEC_NAME = {".mp4": "H.264", ".mkv": "H.264", ".webm": "VP9", ".gif": "GIF"}
LOSSLESS_CODEC_NAME = {".mp4": "H.264", ".mkv": "FFV1", ".webm": "VP9"}

HINT_CUSTOM = "Exact size — may stretch the image"

# Quality hints. Sizes are "much larger" rather than a multiplier: measured
# growth ran from ~6x to ~20x and depends heavily on content.
HINT_COMPRESSED = "18 best quality  ·  30 smallest file"
HINT_GIF = "GIF is limited to 256 colours, so quality settings don't apply."
HINT_LOSSLESS = {
    ".mp4":  "Bit-exact, much larger. Many players can't open lossless MP4 "
             "— MKV is safer.",
    ".mkv":  "Bit-exact, much larger. Keeps transparency. Plays in VLC and mpv.",
    ".webm": "Bit-exact, much larger. Many browsers and players can't open "
             "lossless WebM.",
}

# ─────────────────────────────────────────────
# Design tokens
#
# Colours are (light, dark) pairs. CustomTkinter resolves the pair against the
# current appearance mode, so switching themes is a single
# ctk.set_appearance_mode() call — no per-widget bookkeeping.
# ─────────────────────────────────────────────

BG         = ("#E9E9EE", "#0B0B0D")   # preview canvas
SURFACE    = ("#F4F4F7", "#141417")   # side columns, action bar
RAISED     = ("#FFFFFF", "#1C1C21")   # controls; row hover
HOVER      = ("#E6E6EC", "#24242A")   # hover state of RAISED
LINE       = ("#DADAE1", "#27272E")   # hairline dividers
SELECTED   = ("#DEE5FF", "#1C2240")   # selected queue row

# Segmented controls mark the choice with a neutral thumb, not the accent:
# accent is kept for the primary action, sliders, the selected file and focus.
SEG_TRACK  = ("#E3E3EA", "#1C1C21")
SEG_THUMB  = ("#FFFFFF", "#393943")
SEG_HOVER  = ("#ECECF1", "#25252B")

# Text tiers. TEXT and DIM meet 4.5:1 on every surface above; hierarchy
# between labels and hints comes from size, not from dropping below that.
# FAINT is only for disabled states, decorative marks and icon glyphs, which
# need 3:1 — never for text someone has to read (see tests/test_contrast.py).
TEXT       = ("#16161A", "#ECECF0")   # primary copy
DIM        = ("#5C5C66", "#8D8D96")   # labels, hints, metadata
FAINT      = ("#7A7A85", "#6E6E78")   # disabled, decorative, icon glyphs

ACCENT     = ("#3355E8", "#4463FA")   # interactive fill; ≥4.8:1 with white
ACCENT_HI  = ("#2843C4", "#3A55E0")   # accent hover
ACCENT_TX  = ("#2843C4", "#8FA2FF")   # accent-coloured text on SURFACE
ON_ACCENT  = "#FFFFFF"
FOCUS      = ACCENT_TX                # keyboard focus ring (≥7.6:1 on SURFACE)

OK         = ("#137A3C", "#3DB86A")
WARN       = ("#9A6207", "#D9922B")
DANGER     = ("#C42B22", "#E85C50")
DANGER_HI  = ("#A32019", "#C4453A")

DROP_TINT  = ("#E6EBFE", "#171B2E")   # drag-over fill for the drop zone
CHECK_A    = ("#FFFFFF", "#1E1E23")   # preview transparency checkerboard
CHECK_B    = ("#ECECF0", "#17171B")

# ── Geometry ───────────────────────────────────
# Structure (columns, action bar) is square and full-bleed, divided by
# hairlines. Everything inside it is rounded: large surfaces R_PANEL, controls
# and rows R_CTRL. Nested radii are concentric: inner = outer - gap.

R_PANEL  = 12
R_CTRL   = 8
R_CHECK  = 5
R_PILL   = 3

H_CTRL   = 36
H_MINI   = 30
H_CTA    = 40
H_SLIDER = 18   # track is H_SLIDER - 2*SLIDER_INSET thick
H_BAR    = 2    # progress rail; doubles as the action bar's top divider
SLIDER_INSET = 6
SEG_INSET = 3   # track visible around the thumb

S_XS, S_SM, S_MD, S_LG, S_XL = 4, 8, 12, 16, 24
PAD_X, PAD_Y = 16, 14
BORDER_W = 1

# Keyboard focus shows as a ring RING_W thick, RING_GAP outside the control,
# concentric with its corners (radius + RING). Every focusable control sits
# in a holder inset by RING, so the ring needs no layout change to appear —
# it occupies space the row gap already had (ROW_GAP is the visible gap).
RING_W, RING_GAP = 2, 1
RING = RING_W + RING_GAP
ROW_GAP = S_SM
ROW_PAD = (0, ROW_GAP - 2 * RING)

THUMB = 40       # queue thumbnail; rendered at 2x for sharp high-DPI scaling
LABEL_COL = 74   # width of the form label column
HINT_WRAP = 264  # narrower than the output control column: hints never widen it

# ── Layout ─────────────────────────────────────
# Three columns side by side, so the window is as tall as the tallest column
# rather than the sum of stacked panels. Source and preview share spare width;
# output keeps its natural width so its controls never stretch on wide windows.
COL_SOURCE, COL_PREVIEW, COL_OUTPUT = 300, 300, 360
PREVIEW_MIN = (260, 200)       # requested size of the preview well
SCRUB_W = 160                  # playback position bar under the preview
WIN_DEFAULT = (1240, 760)
WIN_MIN = (1040, 600)          # fits the tallest settings state (see tests)

# ── Typography ─────────────────────────────────
# Populated by init_fonts() once a Tk root exists — tkfont.families() needs one.

F = SimpleNamespace()

_SANS = ("Segoe UI Variable Text", "Segoe UI", "SF Pro Text",
         "Inter", "DejaVu Sans", "Helvetica")
_MONO = ("Cascadia Mono", "Consolas", "SF Mono",
         "JetBrains Mono", "DejaVu Sans Mono", "Courier New")


def _pick_family(candidates, fallback="TkDefaultFont"):
    try:
        available = {f.lower() for f in tkfont.families()}
    except tk.TclError:
        return fallback
    for name in candidates:
        if name.lower() in available:
            return name
    return fallback


def init_fonts():
    sans = _pick_family(_SANS)
    mono = _pick_family(_MONO)
    F.title   = (sans, 13, "bold")
    F.body    = (sans, 12)
    F.body_b  = (sans, 12, "bold")
    F.small   = (sans, 11)
    F.btn     = (sans, 12, "bold")
    F.glyph   = (sans, 20)
    F.mono    = (mono, 11)
    F.mono_b  = (mono, 11, "bold")


def tone(pair):
    """Resolve a (light, dark) pair against the live appearance mode.

    Needed only where a colour leaves the widget tree — e.g. a PIL image.
    """
    return pair[1] if ctk.get_appearance_mode() == "Dark" else pair[0]


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except (json.JSONDecodeError, IOError, OSError):
            pass
    return {}


def save_settings(data):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except (IOError, OSError):
        pass


def _num(value, default, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(lo, min(hi, int(value)))


def make_even(w: int, h: int) -> tuple:
    return w if w % 2 == 0 else w + 1, h if h % 2 == 0 else h + 1


def _even_within(x: int, limit: int) -> int:
    """Nearest even value to x that doesn't exceed limit (rounds up if it can)."""
    x = max(2, min(x, limit))
    if x % 2:
        x = x + 1 if x + 1 <= limit else x - 1
    return max(2, x)


def fit_box(w, h, box_w, box_h):
    """Largest even size fitting inside box while keeping aspect ratio.

    Rounds an odd dimension up where the box allows, as make_even does, so
    even boxes (every encode target) give the same sizes as always; only an
    odd box — like a preview well — gets rounded down instead of overflowing.
    """
    if w <= 0 or h <= 0:
        return _even_within(box_w, box_w), _even_within(box_h, box_h)
    ratio = min(box_w / w, box_h / h)
    return (_even_within(round(w * ratio), box_w),
            _even_within(round(h * ratio), box_h))


def letterbox(img: Image.Image, target: tuple, keep_alpha: bool = False) -> Image.Image:
    """Aspect-fit img inside a target-sized canvas, centred.

    Bars are opaque black and img is composited onto them — unless the output
    keeps alpha, where bars are transparent and img's pixels, alpha included,
    are copied unchanged so every clip in a combined file keeps transparency.
    """
    if img.size == target:
        return img
    w, h = fit_box(img.width, img.height, *target)
    fitted = img.resize((w, h), Image.LANCZOS)
    pos = ((target[0] - w) // 2, (target[1] - h) // 2)
    if keep_alpha:
        canvas = Image.new("RGBA", target, (0, 0, 0, 0))
        canvas.paste(fitted, pos)             # copy, don't blend
    else:
        canvas = Image.new("RGBA", target, (0, 0, 0, 255))
        canvas.paste(fitted, pos, fitted)
    return canvas


def unique_output_path(folder: str, stem: str, ext: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip() or "output"
    path = os.path.join(folder, f"{safe}{ext}")
    n = 1
    while os.path.exists(path):
        path = os.path.join(folder, f"{safe} ({n}){ext}")
        n += 1
    return path


def checkerboard(size: tuple, cell: int = 12, colors=None) -> Image.Image:
    """Transparency checkerboard; colors default to the live theme's pair."""
    light, dark = colors or (tone(CHECK_A), tone(CHECK_B))
    img = Image.new("RGB", size, light)
    draw = ImageDraw.Draw(img)
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            if (x // cell + y // cell) % 2 == 0:
                draw.rectangle([x, y, x + cell - 1, y + cell - 1], fill=dark)
    return img


def rounded_mask(size: tuple, radius: int) -> Image.Image:
    """Anti-aliased alpha mask with rounded corners (drawn 4x, downsampled)."""
    k = 4
    big = Image.new("L", (size[0] * k, size[1] * k), 0)
    ImageDraw.Draw(big).rounded_rectangle(
        [0, 0, big.width - 1, big.height - 1], radius=radius * k, fill=255)
    return big.resize(size, Image.LANCZOS)


def make_thumbs(img: Image.Image, px: int, radius: int) -> tuple:
    """Square rounded thumbnails of img for the (light, dark) themes.

    Centre-cropped to fill, over each theme's checkerboard so transparent
    art stays visible. Returned as a pair so a theme switch needs no rework.
    """
    art = ImageOps.fit(img.convert("RGBA"), (px, px), Image.LANCZOS)
    corners = rounded_mask((px, px), radius)
    thumbs = []
    for i in (0, 1):
        thumb = checkerboard((px, px), cell=max(2, px // 4),
                             colors=(CHECK_A[i], CHECK_B[i])).convert("RGBA")
        thumb.paste(art, (0, 0), art)
        thumb.putalpha(corners)
        thumbs.append(thumb)
    return tuple(thumbs)


def rgba_to_gif_frame(img: Image.Image) -> Image.Image:
    """Quantize RGBA to palette frame with binary transparency at index 255."""
    alpha = img.getchannel("A")
    mask = alpha.point(lambda a: 255 if a <= 128 else 0)
    frame = img.convert("RGB").convert("P", palette=Image.Palette.ADAPTIVE, colors=255)
    frame.paste(255, mask)
    frame.info["transparency"] = 255
    return frame


def short_path(path: str, limit: int = 52) -> str:
    if len(path) <= limit:
        return path
    head, tail = os.path.splitdrive(path)
    parts = tail.strip(os.sep).split(os.sep)
    if len(parts) <= 2:
        return "…" + path[-(limit - 1):]
    return f"{head}{os.sep}…{os.sep}" + os.sep.join(parts[-2:])


# ─────────────────────────────────────────────
# Widget factories — the single source of style
# ─────────────────────────────────────────────

def ringed(parent, build, radius=R_CTRL, **pack):
    """Build a control inside a focus-ring holder; returns (holder, control).

    The holder draws nothing until its control has keyboard focus, so it
    works over any background (see WebPConverterApp._focusable).
    """
    holder = ctk.CTkFrame(parent, fg_color="transparent",
                          corner_radius=radius + RING,
                          border_width=0, border_color=FOCUS)
    control = build(holder)
    control.pack(padx=RING, pady=RING, **pack)
    return holder, control


def _is_enabled(widget) -> bool:
    try:
        return str(widget.cget("state")) != "disabled"
    except (ValueError, tk.TclError, AttributeError):
        # CTkSegmentedButton accepts state in configure but not in cget.
        return getattr(widget, "_state", "normal") != "disabled"


def column(parent, title: str = "", fill=SURFACE):
    """A full-height layout column. Returns (frame, head, body).

    Columns are structure, not content: square and borderless, separated by
    hairline dividers. head is the title row (None without a title), where a
    column's own actions sit on the right.
    """
    # Padding is short by RING: focus-ring holders inset their controls by
    # RING, so controls' visible edges land on PAD_X. Unringed content (the
    # title, labels, hints) is inset by RING itself to share that edge.
    frame = ctk.CTkFrame(parent, fg_color=fill, corner_radius=0, border_width=0)
    head = None
    if title:
        head = ctk.CTkFrame(frame, fg_color="transparent", height=H_MINI + 2 * RING)
        head.pack(fill="x", padx=PAD_X - RING, pady=(PAD_Y - RING, 0))
        head.pack_propagate(False)       # same height with or without actions
        ctk.CTkLabel(head, text=title, font=F.title, text_color=TEXT,
                     height=1).pack(side="left", padx=(RING, 0))
    body = ctk.CTkFrame(frame, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=PAD_X - RING,
              pady=(S_MD - 2 * RING if title else PAD_Y - RING, PAD_Y - RING))
    return frame, head, body


def primary_button(parent, text, command, height=H_CTRL, **kw):
    return ctk.CTkButton(parent, text=text, command=command,
                         fg_color=ACCENT, hover_color=ACCENT_HI,
                         text_color=ON_ACCENT, font=F.btn,
                         corner_radius=R_CTRL, height=height,
                         border_width=0, **kw)


def secondary_button(parent, text, command, height=H_CTRL, **kw):
    # Filled, not outlined: the fill alone separates it from the column.
    return ctk.CTkButton(parent, text=text, command=command,
                         fg_color=RAISED, hover_color=HOVER,
                         text_color=TEXT, font=F.btn,
                         corner_radius=R_CTRL, height=height,
                         border_width=0, **kw)


def ghost_button(parent, text, command, size=26, **kw):
    # HOVER, not RAISED: it must still show on a hovered (RAISED) queue row.
    # Disabled glyphs drop to LINE, well below FAINT, so they read as off.
    return ctk.CTkButton(parent, text=text, command=command,
                         fg_color="transparent", hover_color=HOVER,
                         text_color=FAINT, text_color_disabled=LINE, font=F.body,
                         corner_radius=R_CTRL,
                         width=size, height=size, **kw)


def text_button(parent, text, command, **kw):
    """A quiet action for a column's title row, e.g. "Clear"."""
    return ctk.CTkButton(parent, text=text, command=command,
                         fg_color="transparent", hover_color=RAISED,
                         text_color=DIM, text_color_disabled=FAINT, font=F.body,
                         corner_radius=R_CTRL, height=H_MINI, width=1, **kw)


def segmented(parent, values, variable, command=None):
    seg = ctk.CTkSegmentedButton(
        parent, values=values, variable=variable, command=command,
        fg_color=SEG_TRACK, selected_color=SEG_THUMB,
        selected_hover_color=SEG_THUMB,
        unselected_color=SEG_TRACK, unselected_hover_color=SEG_HOVER,
        text_color=DIM, text_color_disabled=FAINT, font=F.body,
        corner_radius=R_CTRL, height=H_CTRL, border_width=SEG_INSET)

    # The chosen segment's label is TEXT, the rest DIM: a second cue beside
    # the neutral thumb. CTk has no per-segment text colour, hence the
    # private _buttons_dict.
    def emphasise(*_):
        for value, button in seg._buttons_dict.items():
            button.configure(text_color=TEXT if value == variable.get() else DIM)

    variable.trace_add("write", emphasise)
    emphasise()
    return seg


class Tooltip:
    """Hover hint: appears after a short pause, gone on leave or click.

    Drawn inside the window like toasts, so its rounded corners match the rest
    of the UI (bg is the colour its corners sit on). text may be a callable
    returning the current text, or a falsy value to show nothing.
    """
    DELAY_MS = 450
    GAP = 6

    def __init__(self, app, widgets, text, bg=SURFACE, at_pointer=False):
        self.app, self.text, self.bg, self.at_pointer = app, text, bg, at_pointer
        self.anchor = widgets[0]
        self._after_id = None
        self._tip = None
        for w in widgets:
            w.bind("<Enter>", self._schedule, add="+")
            w.bind("<Leave>", self._on_leave, add="+")
            w.bind("<ButtonPress-1>", self.hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self._after_id = self.app.after(self.DELAY_MS, self.show)

    def _cancel(self):
        if self._after_id:
            self.app.after_cancel(self._after_id)
            self._after_id = None

    def _on_leave(self, _event=None):
        # Crossing between a widget's own parts (its canvas and its text)
        # fires Leave too; only hide once the pointer has really left.
        a = self.anchor
        px, py = a.winfo_pointerxy()
        x, y = a.winfo_rootx(), a.winfo_rooty()
        if x <= px < x + a.winfo_width() and y <= py < y + a.winfo_height():
            return
        self.hide()

    def show(self):
        self._after_id = None
        text = self.text() if callable(self.text) else self.text
        if not text or self._tip is not None or not self.anchor.winfo_ismapped():
            return
        app, a = self.app, self.anchor
        tip = ctk.CTkFrame(app, fg_color=RAISED, bg_color=self.bg,
                           corner_radius=R_CTRL, border_width=BORDER_W,
                           border_color=LINE)
        ctk.CTkLabel(tip, text=text, font=F.small, text_color=TEXT,
                     height=1).pack(padx=S_MD, pady=S_SM - 2)
        tip.update_idletasks()

        # Positions are measured in physical pixels; CTk's place() scales.
        scale = ctk.ScalingTracker.get_widget_scaling(tip)
        gap = round(self.GAP * scale)
        tw, th = tip.winfo_reqwidth(), tip.winfo_reqheight()
        if self.at_pointer:
            px, py = a.winfo_pointerxy()
            x = px - app.winfo_rootx() + 2 * gap
            y = py - app.winfo_rooty() + 3 * gap
        else:
            ax, ay = a.winfo_rootx() - app.winfo_rootx(), a.winfo_rooty() - app.winfo_rooty()
            x = ax + (a.winfo_width() - tw) // 2
            y = ay + a.winfo_height() + gap
            if y + th > app.winfo_height() - gap:     # no room below: go above
                y = ay - th - gap
        x = max(gap, min(x, app.winfo_width() - tw - gap))
        y = max(gap, min(y, app.winfo_height() - th - gap))
        tip.place(x=x / scale, y=y / scale)
        tip.lift()
        self._tip = tip

    def hide(self, _event=None):
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None


def form_label(parent, text, row):
    lbl = ctk.CTkLabel(parent, text=text, font=F.body,
                       text_color=DIM, anchor="w", width=LABEL_COL - RING)
    lbl.grid(row=row, column=0, sticky="w", pady=ROW_PAD, padx=(RING, 0))
    return lbl


def hint(parent, text):
    # height=1: size to the text; CTk's default 28px label height is dead space.
    return ctk.CTkLabel(parent, text=text, font=F.small, height=1,
                        text_color=DIM, anchor="w", justify="left")


# ─────────────────────────────────────────────
# App
# ─────────────────────────────────────────────

if _HAS_DND:
    class _AppBase(ctk.CTk, TkinterDnD.DnDWrapper):
        pass
else:
    class _AppBase(ctk.CTk):
        pass


class WebPConverterApp(_AppBase):
    def __init__(self):
        super().__init__()
        init_fonts()

        self._settings = load_settings()
        theme = self._settings.get("theme", "dark")
        self._theme = theme if theme in VALID_THEMES else "dark"
        ctk.set_appearance_mode(self._theme)
        ctk.set_default_color_theme("blue")
        self.configure(fg_color=BG)

        self.title(f"WebP → Video  ·  v{APP_VERSION}")
        # Never open larger than the display — including a size saved on a bigger
        # monitor. CTk geometry is in scaled units; screen size is physical pixels.
        scale = ctk.ScalingTracker.get_window_scaling(self)
        avail_w = int((self.winfo_screenwidth() - 40) / scale)
        avail_h = int((self.winfo_screenheight() - 80) / scale)
        w, h, pos = *WIN_DEFAULT, ""
        geo = self._settings.get("geometry", "")
        m = re.fullmatch(r"(\d{3,5})x(\d{3,5})([+-]\d+[+-]\d+)", geo) \
            if isinstance(geo, str) else None
        if m:
            w, h, pos = int(m[1]), int(m[2]), m[3]
        self.geometry(f"{min(w, avail_w)}x{min(h, avail_h)}{pos}")
        self.minsize(min(WIN_MIN[0], avail_w), min(WIN_MIN[1], avail_h))
        self.resizable(True, True)

        self._set_app_icon()

        # State
        self.webp_files:    list[str] = []
        self.selected_file: str | None = None
        self.file_rows:     dict[str, ctk.CTkFrame] = {}
        self.output_folder  = os.getcwd()
        self._converting    = False
        self._cancel_requested = False
        self._ffmpeg_proc   = None
        self._closing       = False

        # Per-file conversion status: path -> "" | "converting" | "done" | "error"
        self.file_status:        dict[str, str] = {}
        self.file_status_labels: dict[str, ctk.CTkLabel] = {}

        # Per-file metadata cache: path -> {size_mb, frames, w, h, total_ms}
        self.file_meta:        dict[str, dict] = {}
        self.file_meta_labels: dict[str, ctk.CTkLabel] = {}
        self.file_name_labels: dict[str, ctk.CTkLabel] = {}
        self.file_thumbs:       dict[str, ctk.CTkImage] = {}
        self.file_thumb_labels: dict[str, ctk.CTkLabel] = {}

        # Settings vars
        self.output_format     = ctk.StringVar(value=".mp4")
        self.fps_value         = ctk.IntVar(value=16)
        self.combine_videos    = ctk.BooleanVar(value=False)
        self.use_source_timing = ctk.BooleanVar(value=True)
        self.resolution_preset = ctk.StringVar(value="Same Resolution")
        self.crf_value         = ctk.IntVar(value=22)
        self.lossless          = ctk.BooleanVar(value=False)
        self._timing_mode      = ctk.StringVar(value="Original")
        self._quality_mode     = ctk.StringVar(value="Compressed")
        self._locked           = False      # controls locked during conversion
        self._size_error_shown = False
        self._tips: dict[str, Tooltip] = {}
        self.file_remove_btns: dict[str, ctk.CTkButton] = {}

        # Preview state
        self.preview_frames:   list = []   # list of (CTkImage, delay_ms)
        self.preview_index     = 0
        self.preview_running   = False
        self._preview_after_id = None
        self._preview_gen      = 0
        self._preview_fit      = None      # box the current frames were fitted to
        self._resize_after_id  = None

        # Toasts
        self._toasts: list[ctk.CTkFrame] = []

        self._build_layout()
        self.load_previous_settings()
        self.update_files_list()
        self.after(100, self._force_queue_render)
        self._setup_dnd()

        # Keyboard shortcuts
        self.bind("<Control-o>", lambda _e: self.select_webps())
        self.bind("<Control-Return>", lambda _e: self.start_conversion())
        self.bind("<Delete>", self._on_delete)
        self.bind("<ButtonPress-1>", self._on_click_anywhere, add="+")
        self.bind("<Escape>", lambda _e: self._request_cancel())
        self.bind("<space>", self._on_space)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _set_app_icon(self):
        icon_path = resource_path("app_icon.ico")
        if not os.path.exists(icon_path):
            return
        try:
            if sys.platform == "win32":
                self.iconbitmap(icon_path)
            else:
                with Image.open(icon_path) as ico:
                    photo = ImageTk.PhotoImage(ico.convert("RGBA"))
                self.iconphoto(True, photo)
                self._icon_photo = photo
        except Exception:
            pass

    def _setup_dnd(self):
        if not _HAS_DND:
            return
        try:
            self.TkdndVersion = TkinterDnD._require(self)
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)
            self.dnd_bind("<<DropEnter>>", lambda _e: self._set_drop_active(True))
            self.dnd_bind("<<DropLeave>>", lambda _e: self._set_drop_active(False))
        except Exception:
            pass

    def _force_queue_render(self):
        """CTkScrollableFrame can defer first paint until it is scrolled once."""
        try:
            canvas = self.files_list_frame._parent_canvas
            canvas.yview_scroll(1, "units")
            canvas.yview_scroll(-1, "units")
        except AttributeError:
            pass

    # ── Layout skeleton ──────────────────────

    def _build_layout(self):
        # The body's LINE fill shows through 1px gaps between the columns,
        # which is what draws the hairline dividers.
        body = ctk.CTkFrame(self, fg_color=LINE, corner_radius=0)
        body.rowconfigure(0, weight=1)

        # (column, minimum width, share of spare width)
        columns = ((self._build_source(body),  COL_SOURCE,  2),
                   (self._build_preview(body), COL_PREVIEW, 3),
                   (self._build_output(body),  COL_OUTPUT,  0))
        last = len(columns) - 1
        for col, (frame, min_w, weight) in enumerate(columns):
            pad = (0, 0 if col == last else BORDER_W)
            body.columnconfigure(col, weight=weight, minsize=min_w + sum(pad))
            frame.grid(row=0, column=col, sticky="nsew", padx=pad)

        # Built after the body so keyboard focus reaches it last, but packed
        # first so it keeps its height when the window is short.
        self._build_action_bar()
        self.action_bar.pack(side="bottom", fill="x")
        body.pack(side="top", fill="both", expand=True)

        # Widgets whose state depends only on the conversion lock. Anything
        # that also depends on other controls is owned by _sync_controls.
        self._lockable = [
            self.add_files_btn, self.add_folder_btn,
            self.output_folder_btn, self.res_menu, self.combine_check,
            self.custom_res_width, self.custom_res_height,
        ]

    # ── Action bar ───────────────────────────
    # One slim bar replaces the old header and footer: where files go on the
    # left; status and the one accent-filled action on the right. The app's
    # name lives in the window's title bar, which already shows it.

    def _build_action_bar(self):
        bar = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0)
        self.action_bar = bar

        # The progress rail is also the bar's top divider.
        self.progress_bar = ctk.CTkProgressBar(
            bar, fg_color=LINE, progress_color=ACCENT,
            corner_radius=0, border_width=0, height=H_BAR)
        self.progress_bar.pack(side="top", fill="x")
        self._apply_progress(0)

        # Short by RING on each side: the buttons sit in focus-ring holders.
        row = ctk.CTkFrame(bar, fg_color="transparent")
        row.pack(fill="x", padx=PAD_X - RING, pady=S_MD - RING)

        ctk.CTkLabel(row, text="Output", font=F.body, text_color=DIM,
                     height=1).pack(side="left", padx=(RING, 0))
        self.output_folder_label = ctk.CTkLabel(
            row, text="", font=F.mono, text_color=ACCENT_TX,
            anchor="w", cursor="hand2", height=1)
        self.output_folder_label.pack(side="left", padx=(S_SM, S_MD - RING))
        self.output_folder_label.bind("<Button-1>",
                                      lambda _e: self.open_output_folder())
        ring, self.output_folder_btn = ringed(row, lambda h: secondary_button(
            h, "Change", self.select_output_folder, height=H_MINI, width=1))
        ring.pack(side="left")
        self._focus_button(ring, self.output_folder_btn)

        ring, self.convert_btn = ringed(row, lambda h: primary_button(
            h, "▶   Convert", self.start_conversion, height=H_CTA, width=176))
        ring.pack(side="right")
        self._focus_button(ring, self.convert_btn)
        self.status_text = ctk.CTkLabel(row, text="Ready", font=F.body,
                                        text_color=DIM, height=1)
        self.status_text.pack(side="right", padx=(0, S_LG - RING))
        self.status_dot = ctk.CTkLabel(row, text="●", font=F.small,
                                       text_color=DIM, height=1)
        self.status_dot.pack(side="right", padx=(0, S_SM))
        self.progress_text = ctk.CTkLabel(row, text="", font=F.mono,
                                          text_color=DIM, height=1)
        self.progress_text.pack(side="right", padx=(0, S_LG))
        self._status_current = ("Ready", DIM)

        self._tips["output_path"] = Tooltip(self, [self.output_folder_label],
                                            "Open output folder")
        self._tips["convert"] = Tooltip(
            self, [self.convert_btn],
            lambda: "Cancel  ·  Esc" if self._converting
            else "Convert  ·  Ctrl+Enter")

    # ── Column 1: source ─────────────────────

    def _build_source(self, parent):
        frame, head, body = column(parent, "Source")
        self.source_column = frame

        self.queue_count_label = ctk.CTkLabel(head, text="", font=F.mono,
                                              text_color=DIM, height=1)
        self.queue_count_label.pack(side="left", padx=(S_SM, 0))
        ring, self.clear_all_btn = ringed(
            head, lambda h: text_button(h, "Clear", self.clear_file_list))
        ring.pack(side="right")
        self._focus_button(ring, self.clear_all_btn)

        # Equal halves via a uniform grid; width=1 so the buttons ask only for
        # their text, not CTk's 140px default, and never widen the column.
        add_row = ctk.CTkFrame(body, fg_color="transparent")
        add_row.pack(fill="x")
        add_row.columnconfigure((0, 1), weight=1, uniform="add")
        ring, self.add_files_btn = ringed(add_row, lambda h: secondary_button(
            h, "+  Add files", self.select_webps, height=H_MINI, width=1), fill="x")
        ring.grid(row=0, column=0, sticky="ew", padx=(0, S_SM // 2 - RING))
        self._focus_button(ring, self.add_files_btn)
        ring, self.add_folder_btn = ringed(add_row, lambda h: secondary_button(
            h, "Add folder", self.select_folder_of_webps, height=H_MINI, width=1),
            fill="x")
        ring.grid(row=0, column=1, sticky="ew", padx=(S_SM // 2 - RING, 0))
        self._focus_button(ring, self.add_folder_btn)
        self._tips["add_files"] = Tooltip(self, [self.add_files_btn],
                                          "Add .webp files  ·  Ctrl+O")

        # The list area shows the queue — or, while it's empty, a large drop
        # target. update_files_list swaps them, so the target never takes
        # space away from a real queue. It is also the focus ring for both.
        self.list_area = ctk.CTkFrame(body, fg_color="transparent",
                                      corner_radius=R_PANEL + RING,
                                      border_width=0, border_color=FOCUS)
        self.list_area.pack(fill="both", expand=True, pady=(S_MD - 2 * RING, 0))

        # Queue — small requested height: it expands into whatever the column
        # offers, and must not be what sets the window's minimum height.
        self.files_list_frame = ctk.CTkScrollableFrame(
            self.list_area, fg_color="transparent", corner_radius=0, height=120,
            scrollbar_button_color=LINE,
            scrollbar_button_hover_color=FAINT)
        self.files_list_frame._parent_canvas.bind(
            "<Configure>", self._sync_queue_scrollbar, add="+")

        # Border drawn in the fill colour at rest so hover/drag can light it
        # without changing any geometry.
        self.drop_zone = ctk.CTkFrame(
            self.list_area, fg_color=RAISED, corner_radius=R_PANEL,
            border_width=BORDER_W, border_color=RAISED, height=160)

        inner = ctk.CTkFrame(self.drop_zone, fg_color="transparent")
        inner.place(relx=0.5, rely=0.5, anchor="center")
        self.drop_glyph = ctk.CTkLabel(inner, text="+", font=F.glyph,
                                       text_color=ACCENT_TX)
        self.drop_glyph.pack()
        self.drop_title = ctk.CTkLabel(
            inner,
            text="Drop .webp files here" if _HAS_DND else "Add .webp files",
            font=F.body_b, text_color=TEXT)
        self.drop_title.pack()
        self.drop_hint = ctk.CTkLabel(inner, text="or click to browse  ·  Ctrl+O",
                                      font=F.small, text_color=DIM)
        self.drop_hint.pack()

        for w in (self.drop_zone, inner, self.drop_glyph,
                  self.drop_title, self.drop_hint):
            w.configure(cursor="hand2")
            w.bind("<Button-1>", lambda _e: self.select_webps())
            w.bind("<Enter>", lambda _e: self._hover_drop(True))
            w.bind("<Leave>", lambda _e: self._hover_drop(False))

        # Keyboard: the queue walks with arrows; the empty drop target
        # browses on Space/Enter. Only one of them is ever on screen.
        self._focusable(self.list_area, self.files_list_frame, {
            "<Up>": lambda: self._select_offset(-1),
            "<Down>": lambda: self._select_offset(1),
            "<Home>": lambda: self._select_index(0),
            "<End>": lambda: self._select_index(-1),
        }, enabled=lambda: bool(self.webp_files))
        self._focusable(self.list_area, self.drop_zone, {
            "<space>": self.select_webps, "<Return>": self.select_webps,
        }, enabled=lambda: not self._locked)
        return frame

    def _hover_drop(self, on: bool):
        if self._converting:
            return
        self.drop_zone.configure(border_color=ACCENT if on else RAISED)

    def _set_drop_active(self, on: bool):
        """Drag-over feedback: the whole Source column is the drop target."""
        self.source_column.configure(fg_color=DROP_TINT if on else SURFACE)
        # The queue paints on a plain Tk canvas, which the column's colour
        # change doesn't reach; its own configure repaints canvas and rows.
        self.files_list_frame.configure(fg_color=DROP_TINT if on else "transparent")
        self.drop_zone.configure(border_color=ACCENT if on else RAISED)

    def _sync_queue_scrollbar(self, _event=None):
        """Show the queue's scrollbar only while the list overflows.

        CTkScrollableFrame always shows it, and in this chrome-light layout an
        idle track is noise. Relies on CTk internals (_parent_canvas,
        _scrollbar), so it degrades to CTk's default if those move.
        """
        lst = self.files_list_frame
        try:
            if lst.winfo_reqheight() > lst._parent_canvas.winfo_height():
                lst._scrollbar.grid()
            else:
                lst._scrollbar.grid_remove()
        except (AttributeError, tk.TclError):
            pass

    # ── Column 2: preview ────────────────────

    def _build_preview(self, parent):
        # An open canvas: no title, no card — frames sit straight on it.
        frame, _, body = column(parent, fill=BG)

        # The well takes whatever space the column gives it. The label is
        # placed, not packed, so the image never feeds back into the well's
        # requested size; frames are re-fitted when the well is resized.
        self.preview_well = ctk.CTkFrame(
            body, fg_color="transparent", corner_radius=0,
            width=PREVIEW_MIN[0], height=PREVIEW_MIN[1])
        self.preview_well.pack(side="top", fill="both", expand=True)
        self.preview_well.bind("<Configure>", self._on_preview_resize)
        self.preview_well.bind("<Button-1>", lambda _e: self._toggle_preview())

        self.preview_label = ctk.CTkLabel(
            self.preview_well, text="Select a file to preview",
            font=F.small, text_color=DIM, fg_color="transparent")
        self.preview_label.place(relx=0.5, rely=0.5, anchor="center")
        self.preview_label.bind("<Button-1>", lambda _e: self._toggle_preview())
        self._tips["preview"] = Tooltip(
            self, [self.preview_well, self.preview_label],
            lambda: self.preview_frames and (
                "Click or Space to pause" if self.preview_running
                else "Click or Space to play"),
            bg=BG, at_pointer=True)

        # Fixed wrap width: a status line must never push the column wider,
        # or the well moves under frames that were just fitted to it.
        self.preview_info = ctk.CTkLabel(body, text="", font=F.mono,
                                         text_color=DIM, justify="center",
                                         wraplength=PREVIEW_MIN[0], height=1)
        self.preview_info.pack(side="bottom", fill="x", pady=(S_SM, 0))

        # Playback position. Always packed, so showing it never resizes the
        # well; with no clip it is painted in the canvas colour.
        self.preview_bar = ctk.CTkProgressBar(
            body, fg_color=BG, progress_color=BG, corner_radius=R_PILL,
            border_width=0, height=3, width=SCRUB_W)
        self.preview_bar.pack(side="bottom", pady=(S_MD, 0))
        self.preview_bar.set(0)
        self._preview_ends: list[float] = []
        return frame

    # ── Column 3: output ─────────────────────

    def _build_output(self, parent):
        out_frame, head, form = column(parent, "Output")
        ring, self.theme_btn = ringed(head, lambda h: ghost_button(
            h, "☾" if self._theme == "dark" else "☀",
            self._toggle_theme, size=H_MINI))
        self.theme_btn.configure(text_color=DIM)
        ring.pack(side="right")
        self._focus_button(ring, self.theme_btn)
        self._tips["theme"] = Tooltip(
            self, [self.theme_btn],
            lambda: f"Switch to {'light' if self._theme == 'dark' else 'dark'} theme")

        form.columnconfigure(0, weight=0, minsize=LABEL_COL)
        form.columnconfigure(1, weight=1)

        # Format
        form_label(form, "Format", 0)
        format_changed = lambda _fmt: self._sync_controls()
        ring, self.format_seg = ringed(form, lambda h: segmented(
            h, list(VALID_FORMATS), self.output_format, format_changed), fill="x")
        ring.grid(row=0, column=1, sticky="ew", pady=ROW_PAD)
        self._focus_segmented(ring, self.format_seg, self.output_format, format_changed)

        # Size
        form_label(form, "Size", 1)
        ring, self.res_menu = ringed(form, lambda h: ctk.CTkOptionMenu(
            h, values=list(VALID_RESOLUTIONS),
            variable=self.resolution_preset, command=self.toggle_custom_res_entry,
            fg_color=RAISED, button_color=RAISED, button_hover_color=HOVER,
            text_color=TEXT, font=F.body,
            dropdown_fg_color=SURFACE, dropdown_hover_color=HOVER,
            dropdown_text_color=TEXT, dropdown_font=F.body,
            corner_radius=R_CTRL, height=H_CTRL), fill="x")
        ring.grid(row=1, column=1, sticky="ew", pady=ROW_PAD)
        self._focus_option(ring, self.res_menu, self.resolution_preset,
                           self.toggle_custom_res_entry)

        # W/H labels stay visible while typing (a placeholder alone vanishes).
        # The hint beneath doubles as the error line, so errors appear next to
        # the field without moving anything. Kept inside the control column so
        # showing Custom never widens the output panel.
        self.custom_res_row = ctk.CTkFrame(form, fg_color="transparent")
        entries = ctk.CTkFrame(self.custom_res_row, fg_color="transparent")
        entries.pack(anchor="w")
        self.custom_res_width = self._size_entry(entries, "W", "1920")
        self.custom_res_height = self._size_entry(entries, "H", "1080",
                                                  pad_left=S_MD)
        hint(entries, "px").pack(side="left", padx=(S_SM, 0))
        self.custom_hint = hint(self.custom_res_row, HINT_CUSTOM)
        self.custom_hint.pack(anchor="w", pady=(S_XS, 0))

        # Quality and Timing share one shape: a mode switch, then the slider it
        # governs. The slider's readout carries its unit, so it needs no label.
        form_label(form, "Quality", 3)
        ring, self.quality_seg = ringed(form, lambda h: segmented(
            h, ["Compressed", "Lossless"], self._quality_mode,
            self._on_quality_mode), fill="x")
        ring.grid(row=3, column=1, sticky="ew", pady=ROW_PAD)
        self._focus_segmented(ring, self.quality_seg, self._quality_mode,
                              self._on_quality_mode)
        self.crf_slider = self._slider_row(
            form, row=4, var=self.crf_value, from_=18, to=30, steps=12,
            suffix="CRF", attr="crf_label")

        # The hint changes with format and mode; reserving two lines up front
        # keeps the rows below from jumping when it does.
        hint_gap = S_MD - RING           # the Timing control below is ringed
        self.quality_hint = hint(form, "\n")
        self.quality_hint.configure(wraplength=HINT_WRAP)
        self.quality_hint.grid(row=5, column=1, sticky="nw",
                               pady=(0, hint_gap), padx=(RING, 0))
        form.update_idletasks()
        # Physical pixels on both sides: the measured height, and CTk's pady
        # after scaling (row minsize is a raw Tk value).
        scale = ctk.ScalingTracker.get_widget_scaling(form)
        form.rowconfigure(5, minsize=self.quality_hint.winfo_reqheight()
                                     + round(hint_gap * scale))

        form_label(form, "Timing", 6)
        ring, self.timing_seg = ringed(form, lambda h: segmented(
            h, ["Original", "Fixed FPS"], self._timing_mode,
            self._on_timing_mode), fill="x")
        ring.grid(row=6, column=1, sticky="ew", pady=ROW_PAD)
        self._focus_segmented(ring, self.timing_seg, self._timing_mode,
                              self._on_timing_mode)
        self.fps_slider = self._slider_row(
            form, row=7, var=self.fps_value, from_=1, to=60, steps=59,
            suffix="FPS", attr="fps_label", pady=(0, S_MD - 2 * RING))

        # Combine
        ring, self.combine_check = ringed(form, lambda h: ctk.CTkCheckBox(
            h, text="Combine all files into a single output",
            variable=self.combine_videos,
            text_color=TEXT, font=F.body,
            checkmark_color=ON_ACCENT, fg_color=ACCENT, hover_color=ACCENT_HI,
            border_color=FAINT, border_width=BORDER_W,
            corner_radius=R_CHECK,
            checkbox_width=18, checkbox_height=18))
        ring.grid(row=8, column=0, columnspan=2, sticky="w")
        self._focusable(ring, self.combine_check,
                        {"<space>": self.combine_check.toggle})
        self.combine_check.configure(command=self._refresh_summary)

        # Result: what Convert will write for the selected file, kept at the
        # foot of the column so the settings above never move.
        form.rowconfigure(9, weight=1, minsize=S_MD)
        card = ctk.CTkFrame(form, fg_color=RAISED, corner_radius=R_PANEL)
        card.grid(row=10, column=0, columnspan=2, sticky="sew", padx=RING,
                  pady=(0, RING))
        ctk.CTkLabel(card, text="Result", font=F.small, text_color=DIM,
                     height=1, anchor="w").pack(fill="x", padx=S_MD,
                                                pady=(S_MD - 2, 0))
        self.summary_title = ctk.CTkLabel(card, text="", font=F.body_b,
                                          text_color=TEXT, height=1, anchor="w")
        self.summary_title.pack(fill="x", padx=S_MD, pady=(S_XS, 0))
        self.summary_detail = ctk.CTkLabel(
            card, text="", font=F.mono, text_color=DIM, height=1, anchor="w",
            justify="left", wraplength=COL_OUTPUT - 2 * PAD_X - 2 * S_MD)
        self.summary_detail.pack(fill="x", padx=S_MD, pady=(S_XS, S_MD))

        return out_frame

    def _size_entry(self, parent, label, example, pad_left=0):
        ctk.CTkLabel(parent, text=label, font=F.body, text_color=DIM,
                     height=1).pack(side="left", padx=(pad_left, S_SM))
        # Filled like the other controls; the border is drawn in the fill
        # colour until it has something to say (an error). Focus is the
        # holder's ring, so an error border and a focus ring never compete.
        ring, entry = ringed(parent, lambda h: ctk.CTkEntry(
            h, width=76, placeholder_text=example,
            fg_color=RAISED, border_color=RAISED, border_width=BORDER_W,
            placeholder_text_color=DIM, text_color=TEXT,
            font=F.body, corner_radius=R_CTRL, height=H_MINI))
        ring.pack(side="left")
        self._focusable(ring, entry._entry)
        # Leaving a field flags a bad value; typing only clears or updates an
        # error already shown, so half-typed numbers ("1" on the way to
        # "128") are never flagged.
        entry.bind("<FocusOut>", self._on_size_blur)
        entry.bind("<KeyRelease>", self._on_size_key)
        return entry

    def _on_size_blur(self, _event=None):
        self._check_size_fields(quiet_if_empty=True)

    def _on_size_key(self, _event=None):
        if self._size_error_shown:
            self._check_size_fields(quiet_if_empty=True)
        self._refresh_summary()

    def _size_error(self, entry, name: str):
        value = entry.get().strip()
        if not value:
            return f"Enter a {name.lower()}"
        if not value.isdigit():
            return f"{name} must be a whole number"
        if not 2 <= int(value) <= MAX_DIMENSION:
            return f"{name} must be 2–{MAX_DIMENSION} px"
        return None

    def _check_size_fields(self, quiet_if_empty=False):
        """Mark invalid custom-size fields inline; return the first bad entry.

        quiet_if_empty leaves empty fields unflagged — used while the user is
        still filling the form in, as opposed to when they press Convert.
        """
        first = None
        for entry, name in ((self.custom_res_width, "Width"),
                            (self.custom_res_height, "Height")):
            error = self._size_error(entry, name)
            if error and quiet_if_empty and not entry.get().strip():
                error = None
            entry.configure(border_color=DANGER if error else RAISED)
            if error and first is None:
                first = (entry, error)
        self._size_error_shown = first is not None
        if first:
            self.custom_hint.configure(text=f"✕  {first[1]}", text_color=DANGER)
            return first[0]
        self.custom_hint.configure(text=HINT_CUSTOM, text_color=DIM)
        return None

    def _clear_size_errors(self):
        for entry in (self.custom_res_width, self.custom_res_height):
            entry.configure(border_color=RAISED)
        self.custom_hint.configure(text=HINT_CUSTOM, text_color=DIM)
        self._size_error_shown = False

    def _slider_row(self, parent, row, var, from_, to, steps, suffix, attr,
                    pady=(0, S_SM - RING)):
        line = ctk.CTkFrame(parent, fg_color="transparent")
        line.grid(row=row, column=1, sticky="ew", pady=pady)

        val_lbl = ctk.CTkLabel(line, text=f"{var.get()} {suffix}",
                               font=F.mono_b, text_color=ACCENT_TX,
                               width=62, height=1, anchor="e")
        val_lbl.pack(side="right", padx=(0, RING))
        setattr(self, attr, val_lbl)

        ring, slider = ringed(line, lambda h: ctk.CTkSlider(
            h, from_=from_, to=to, number_of_steps=steps, variable=var,
            fg_color=LINE, progress_color=ACCENT,
            button_color=ACCENT, button_hover_color=ACCENT_HI,
            corner_radius=R_PILL,
            height=H_SLIDER, border_width=SLIDER_INSET), fill="x")
        ring.pack(side="left", fill="x", expand=True, padx=(0, S_MD - RING))

        def changed(value, lbl=val_lbl, sfx=suffix):
            self._on_slider_change(lbl, sfx, value)
        slider.configure(command=changed)
        self._focus_slider(ring, slider, var, from_, to, changed)
        return slider

    def _on_slider_change(self, lbl, suffix, value):
        lbl.configure(text=f"{int(float(value))} {suffix}")
        if suffix == "FPS":
            self._refresh_meta_labels()

    def _on_timing_mode(self, choice):
        self.use_source_timing.set(choice == "Original")
        self._sync_controls()

    def _on_quality_mode(self, choice):
        self.lossless.set(choice == "Lossless")
        self._sync_controls()

    # A disabled control must not read as live: state and colour move together.

    @staticmethod
    def _style_slider(slider, label, enabled: bool):
        slider.configure(state="normal" if enabled else "disabled",
                         progress_color=ACCENT if enabled else LINE,
                         button_color=ACCENT if enabled else FAINT)
        label.configure(text_color=ACCENT_TX if enabled else FAINT)

    @staticmethod
    def _style_segmented(seg, enabled: bool):
        # Disabled: the thumb sinks into the track, so nothing looks chosen.
        thumb = SEG_THUMB if enabled else SEG_TRACK
        seg.configure(state="normal" if enabled else "disabled",
                      selected_color=thumb, selected_hover_color=thumb)

    def _quality_hint(self) -> str:
        fmt = self.output_format.get()
        if fmt == ".gif":
            return HINT_GIF
        return HINT_LOSSLESS[fmt] if self.lossless.get() else HINT_COMPRESSED

    def _output_summary(self) -> tuple:
        """(file name, details) of what Convert would write right now."""
        files = self.webp_files
        if not files:
            return "Nothing queued", "Add files to see what you'll get"
        combined = self.combine_videos.get() and len(files) > 1
        source = files[0] if combined else (self.selected_file or files[0])
        fmt = self.output_format.get()
        lossless = self.lossless.get() and fmt != ".gif"
        stem = "combined" if combined else Path(source).stem
        name = os.path.basename(unique_output_path(self.output_folder, stem, fmt))
        if len(name) > 38:
            name = name[:22] + "…" + name[-15:]

        parts = [f"{len(files)} clips"] if combined else []
        meta = self.file_meta.get(source)
        if meta is None:
            parts.append("reading…")
        elif meta["frames"] == 0:
            return name, "This file can't be read"
        else:
            preset = self.resolution_preset.get()
            custom = [e.get().strip() for e in (self.custom_res_width,
                                                self.custom_res_height)]
            if preset == "Custom" and not all(
                    v.isdigit() and 2 <= int(v) <= MAX_DIMENSION for v in custom):
                parts.append("size not set")
            else:
                settings = {"resolution": preset}
                if preset == "Custom":
                    settings["custom_w"], settings["custom_h"] = map(int, custom)
                parts.append("{}×{}".format(
                    *self._target_size(meta["w"], meta["h"], settings)))
        parts.append(f"{LOSSLESS_CODEC_NAME[fmt]} lossless" if lossless
                     else CODEC_NAME[fmt])
        parts.append("original timing" if self.use_source_timing.get()
                     else f"{max(1, self.fps_value.get())} fps")
        if keeps_alpha(fmt, lossless):
            parts.append("keeps transparency")
        return name, " · ".join(parts)

    def _refresh_summary(self):
        if not hasattr(self, "summary_title"):
            return                      # still building the window
        title, detail = self._output_summary()
        self.summary_title.configure(text=title)
        self.summary_detail.configure(text=detail)

    def _sync_controls(self):
        """Apply every dependency between controls — the only place that does.

        The conversion lock disables everything; otherwise a GIF target
        disables Quality, Lossless disables the CRF slider, Original timing
        disables the Rate slider, and an empty queue disables Clear.
        """
        locked = self._locked
        gif = self.output_format.get() == ".gif"
        lossless = self.lossless.get() and not gif
        self.clear_all_btn.configure(
            state="disabled" if locked or not self.webp_files else "normal")
        for remove_btn in self.file_remove_btns.values():
            remove_btn.configure(state="disabled" if locked else "normal")
        self._style_segmented(self.format_seg, not locked)
        self._style_segmented(self.timing_seg, not locked)
        self._style_segmented(self.quality_seg, not (locked or gif))
        self._style_slider(self.crf_slider, self.crf_label,
                           not (locked or gif or lossless))
        self._style_slider(self.fps_slider, self.fps_label,
                           not (locked or self.use_source_timing.get()))
        self.quality_hint.configure(text=self._quality_hint())
        self._refresh_meta_labels()

    # ── Keyboard ─────────────────────────────
    # CTk widgets have no keyboard support, so each focusable control gets
    # it here: a place in the Tab order (skipped while disabled), a ring
    # while focused, and its keys. Tab order is creation order, which follows
    # the visual order: Source, Output, then the action bar.

    def _focusable(self, holder, target, keys=None, enabled=None):
        """target: the Tk widget that takes focus — a CTk widget's own frame,
        or a CTkEntry's inner entry. Handlers end in "break" so a key a
        control uses (Space on a button) never also fires a window shortcut.
        """
        is_enabled = enabled or (lambda: _is_enabled(target))
        if not isinstance(target, tk.Entry):
            # A callable takefocus replaces Tk's own visibility check, so it
            # must do that check too — or hidden widgets stay in the Tab order.
            tk.Frame.configure(target, takefocus=lambda _w: 1 if (
                target.winfo_viewable() and is_enabled()) else 0)
        tk.Misc.bind(target, "<FocusIn>",
                     lambda _e: holder.configure(border_width=RING_W), add="+")
        tk.Misc.bind(target, "<FocusOut>",
                     lambda _e: holder.configure(border_width=0), add="+")
        for sequence, action in (keys or {}).items():
            tk.Misc.bind(target, sequence,
                         lambda _e, act=action: (is_enabled() and act(), "break")[1])

    def _focus_button(self, holder, button):
        self._focusable(holder, button,
                        {"<space>": button.invoke, "<Return>": button.invoke})

    @staticmethod
    def _step_value(values, current, delta):
        values = list(values)
        i = values.index(current) if current in values else 0
        j = max(0, min(len(values) - 1, i + delta))
        return values[j] if j != i else None

    def _focus_segmented(self, holder, seg, variable, command):
        def step(delta):
            new = self._step_value(seg.cget("values"), variable.get(), delta)
            if new is not None:
                seg.set(new)
                if command:
                    command(new)
        self._focusable(holder, seg, {"<Left>": lambda: step(-1),
                                      "<Right>": lambda: step(1)})

    def _focus_slider(self, holder, slider, var, lo, hi, on_change):
        def nudge(delta):
            value = max(lo, min(hi, int(round(var.get())) + delta))
            slider.set(value)
            on_change(value)
        self._focusable(holder, slider, {
            "<Left>": lambda: nudge(-1), "<Down>": lambda: nudge(-1),
            "<Right>": lambda: nudge(1), "<Up>": lambda: nudge(1)})

    def _focus_option(self, holder, menu, variable, command):
        def step(delta):
            new = self._step_value(menu.cget("values"), variable.get(), delta)
            if new is not None:
                variable.set(new)
                command(new)

        def open_menu():
            try:                    # CTk has no public way to open it
                menu._open_dropdown_menu()
            except AttributeError:
                pass
        self._focusable(holder, menu, {
            "<Up>": lambda: step(-1), "<Down>": lambda: step(1),
            "<Return>": open_menu, "<space>": open_menu})

    def _select_offset(self, delta):
        if not self.webp_files:
            return
        files = self.webp_files
        i = files.index(self.selected_file) if self.selected_file in files else -1
        self._select_index(max(0, min(len(files) - 1, i + delta)))

    def _select_index(self, index):
        path = self.webp_files[index]
        if path != self.selected_file:
            self.set_selected_file(path)
            self.show_preview(path)
        self._scroll_into_view(self.file_rows.get(path))

    def _scroll_into_view(self, row):
        if row is None or not row.winfo_exists():
            return
        self.update_idletasks()
        canvas = self.files_list_frame._parent_canvas
        total = self.files_list_frame.winfo_height()
        if total <= 0:
            return
        top, bottom = canvas.yview()
        y0 = row.winfo_y() / total
        y1 = (row.winfo_y() + row.winfo_height()) / total
        if y0 < top:
            canvas.yview_moveto(y0)
        elif y1 > bottom:
            canvas.yview_moveto(y1 - (bottom - top))

    def _on_delete(self, event):
        # In a text field Delete edits the text; it must not also remove the
        # selected file from the queue. event.widget is whatever had focus.
        if isinstance(event.widget, (tk.Entry, tk.Text)):
            return
        self._remove_selected()

    def _on_click_anywhere(self, event):
        # Rings show keyboard focus, not the last thing clicked — the same
        # rule as the web's :focus-visible. Text fields keep click focus.
        if not isinstance(event.widget, (tk.Entry, tk.Text)):
            self.focus_set()

    # ── Theme ────────────────────────────────

    def _toggle_theme(self):
        self._theme = "light" if self._theme == "dark" else "dark"
        ctk.set_appearance_mode(self._theme)
        self.theme_btn.configure(text="☾" if self._theme == "dark" else "☀")
        # The preview checkerboard is a baked PIL image — rebuild it in place.
        if self.selected_file:
            self.show_preview(self.selected_file, keep_current=True)
        self.save_current_settings()

    # ── Settings persistence ─────────────────

    def save_current_settings(self):
        save_settings({
            "fps":           self.fps_value.get(),
            "format":        self.output_format.get(),
            "crf":           self.crf_value.get(),
            "resolution":    self.resolution_preset.get(),
            "combine":       bool(self.combine_videos.get()),
            "source_timing": bool(self.use_source_timing.get()),
            "lossless":      bool(self.lossless.get()),
            "custom_w":      self.custom_res_width.get(),
            "custom_h":      self.custom_res_height.get(),
            "output_folder": self.output_folder,
            "theme":         self._theme,
            "geometry":      self.geometry(),
        })

    def load_previous_settings(self):
        s = self._settings
        self.fps_value.set(_num(s.get("fps", 16), 16, 1, 60))
        fmt = s.get("format", ".mp4")
        self.output_format.set(fmt if fmt in VALID_FORMATS else ".mp4")
        self.crf_value.set(_num(s.get("crf", 22), 22, 18, 30))
        res = s.get("resolution", "Same Resolution")
        self.resolution_preset.set(res if res in VALID_RESOLUTIONS else "Same Resolution")
        self.combine_videos.set(bool(s.get("combine", False)))
        self.use_source_timing.set(bool(s.get("source_timing", True)))
        self._timing_mode.set("Original" if self.use_source_timing.get() else "Fixed FPS")
        self.lossless.set(bool(s.get("lossless", False)))
        self._quality_mode.set("Lossless" if self.lossless.get() else "Compressed")
        folder = s.get("output_folder", os.getcwd())
        self.output_folder = folder if isinstance(folder, str) and os.path.isdir(folder) else os.getcwd()
        for key, entry in (("custom_w", self.custom_res_width),
                           ("custom_h", self.custom_res_height)):
            val = s.get(key, "")
            if isinstance(val, str) and val.isdigit():
                entry.insert(0, val)
        self._refresh_output_label()
        self.fps_label.configure(text=f"{self.fps_value.get()} FPS")
        self.crf_label.configure(text=f"{self.crf_value.get()} CRF")
        self.toggle_custom_res_entry(self.resolution_preset.get())
        self._sync_controls()

    # ── UI helpers ───────────────────────────

    def _refresh_output_label(self):
        self.output_folder_label.configure(text=short_path(self.output_folder))
        self._refresh_summary()

    def _set_status(self, text: str, color=DIM):
        self.status_text.configure(text=text, text_color=color)
        self.status_dot.configure(text_color=color)

    def _commit_status(self, text: str, color=DIM):
        self._status_current = (text, color)
        self._set_status(text, color)

    def _restore_status(self):
        self._set_status(*self._status_current)

    def toggle_custom_res_entry(self, choice):
        if choice == "Custom":
            self.custom_res_row.grid(row=2, column=1, sticky="w",
                                     pady=(0, S_SM - RING), padx=(RING, 0))
        else:
            self.custom_res_row.grid_remove()
            self._clear_size_errors()      # a hidden field can't show its error
        self._refresh_summary()

    def _set_controls_enabled(self, enabled: bool):
        self._locked = not enabled
        state = "normal" if enabled else "disabled"
        for widget in self._lockable:
            try:
                widget.configure(state=state)
            except (tk.TclError, ValueError):
                pass
        fill = RAISED if enabled else SURFACE
        self.drop_zone.configure(fg_color=fill, border_color=fill)
        self._sync_controls()

    def _ui(self, fn, *args, **kwargs):
        """Schedule a UI call from any thread; safe across window close."""
        if self._closing:
            return
        def call():
            if self._closing:
                return
            try:
                fn(*args, **kwargs)
            except tk.TclError:
                pass
        try:
            self.after(0, call)
        except RuntimeError:
            pass

    def _apply_progress(self, fraction: float):
        """At zero, hide the fill so the rail reads as a plain divider."""
        self.progress_bar.set(fraction)
        self.progress_bar.configure(
            progress_color=LINE if fraction <= 0 else ACCENT)

    def _ui_progress(self, fraction: float, stage: str = ""):
        fraction = max(0.0, min(1.0, fraction))
        pct = int(fraction * 100)
        key = (pct, stage)
        if key == getattr(self, "_last_progress", None):
            return
        self._last_progress = key
        text = f"{stage}  ·  {pct}%" if stage else f"{pct}%"
        self._ui(self._apply_progress, fraction)
        self._ui(self.progress_text.configure, text=text)

    def _refresh_convert_btn(self):
        if self._converting:
            return
        n = len(self.webp_files)
        label = "▶   Convert" if not n else f"▶   Convert {n} file{'s' if n != 1 else ''}"
        self.convert_btn.configure(text=label)

    # ── File selection ───────────────────────

    def select_webps(self):
        if self._converting:
            return
        files = filedialog.askopenfilenames(
            filetypes=[("WebP files", "*.webp"), ("All files", "*.*")])
        if files:
            self._add_files(files)

    def select_folder_of_webps(self):
        if self._converting:
            return
        folder = filedialog.askdirectory(title="Add all WebP files from folder")
        if not folder:
            return
        found = sorted(
            str(p) for p in Path(folder).iterdir()
            if p.is_file() and p.suffix.lower() == ".webp"
        )
        if found:
            self._add_files(found)
        else:
            self.show_toast("No .webp files in that folder", kind="warn")

    def _add_files(self, files):
        existing = {os.path.normcase(f) for f in self.webp_files}
        added, skipped = [], 0
        for f in files:
            f = os.path.abspath(f)
            key = os.path.normcase(f)
            if key in existing:
                skipped += 1
            elif f.lower().endswith(".webp") and os.path.isfile(f):
                added.append(f)
                existing.add(key)
            else:
                skipped += 1
        if not added:
            if skipped:
                self.show_toast("Nothing added — duplicates or not .webp", kind="warn")
            return
        self.webp_files.extend(added)
        self.update_files_list()
        self._build_metas_async(added)
        self.set_selected_file(added[0])
        self.show_preview(added[0])
        if skipped:
            self.show_toast(f"Added {len(added)}, skipped {skipped}", kind="info")

    def _on_drop(self, event):
        self._set_drop_active(False)
        if self._converting:
            return
        try:
            raw = self.tk.splitlist(event.data)
        except tk.TclError:
            return
        paths = []
        for p in raw:
            if os.path.isdir(p):
                paths.extend(sorted(
                    str(x) for x in Path(p).iterdir()
                    if x.is_file() and x.suffix.lower() == ".webp"))
            else:
                paths.append(p)
        self._add_files(paths)

    def select_output_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_folder = folder
            self._refresh_output_label()
            self.save_current_settings()

    # ── File metadata ────────────────────────

    def _build_metas_async(self, paths: list):
        def work():
            for path in paths:
                if self._closing:
                    return
                meta = self._read_meta(path)
                self._ui(self._apply_meta, path, meta)
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _read_meta(path: str) -> dict:
        meta = {"size_mb": 0.0, "frames": 0, "w": 0, "h": 0, "total_ms": 0,
                "thumbs": None}
        try:
            meta["size_mb"] = os.path.getsize(path) / (1024 * 1024)
        except OSError:
            pass
        try:
            with Image.open(path) as im:
                meta["w"], meta["h"] = im.width, im.height
                meta["thumbs"] = make_thumbs(im, 2 * THUMB, 2 * (R_CTRL - 2))
                n = getattr(im, "n_frames", 1)
                total = 0
                for i in range(n):
                    im.seek(i)
                    im.load()  # duration only populated after load
                    total += int(im.info.get("duration", 0) or 0)
                meta["frames"] = n
                meta["total_ms"] = total
        except Exception:
            pass
        return meta

    def _apply_meta(self, path: str, meta: dict):
        if path not in self.webp_files:
            return
        thumbs = meta.pop("thumbs", None)
        self.file_meta[path] = meta
        label = self.file_meta_labels.get(path)
        if label and label.winfo_exists():
            label.configure(text=self._format_meta(path))
        if thumbs:
            self.file_thumbs[path] = ctk.CTkImage(
                light_image=thumbs[0], dark_image=thumbs[1], size=(THUMB, THUMB))
            self._show_thumb(self.file_thumb_labels.get(path), path)
        self._refresh_summary()

    def _show_thumb(self, label, path):
        image = self.file_thumbs.get(path)
        if image and label and label.winfo_exists():
            label.configure(image=image, fg_color="transparent")

    def _format_meta(self, path: str) -> str:
        meta = self.file_meta.get(path)
        if meta is None:
            return "reading…"
        if meta["frames"] == 0:
            return f"{meta['size_mb']:.1f} MB  ·  unreadable"
        fps = max(1, self.fps_value.get())
        if self.use_source_timing.get() and meta["total_ms"] > 0:
            duration = meta["total_ms"] / 1000
        else:
            duration = meta["frames"] / fps
        # Frame count is in the preview's caption; the row keeps what fits
        # beside a thumbnail at the column's narrowest.
        return (f"{meta['size_mb']:.1f} MB  ·  {meta['w']}×{meta['h']}"
                f"  ·  {duration:.1f}s")

    def _refresh_meta_labels(self):
        for path, label in self.file_meta_labels.items():
            if label.winfo_exists():
                label.configure(text=self._format_meta(path))
        self._refresh_summary()

    # ── File list UI ─────────────────────────

    def update_files_list(self):
        for widget in self.files_list_frame.winfo_children():
            widget.destroy()
        self.file_rows = {}
        self.file_status_labels = {}
        self.file_meta_labels = {}
        self.file_name_labels = {}
        self.file_thumb_labels = {}
        self.file_remove_btns = {}

        count = len(self.webp_files)
        self.queue_count_label.configure(text=str(count) if count else "")
        self._refresh_convert_btn()
        self._sync_controls()

        # Empty: the whole list area becomes one large drop target.
        if not count:
            self.files_list_frame.pack_forget()
            self.drop_zone.pack(fill="both", expand=True, padx=RING, pady=RING)
            return
        self.drop_zone.pack_forget()
        self.files_list_frame.pack(fill="both", expand=True, padx=RING, pady=RING)

        for idx, file in enumerate(self.webp_files):
            is_selected = file == self.selected_file

            # Rows have no outline: a fill appears on hover and on selection.
            item = ctk.CTkFrame(
                self.files_list_frame,
                fg_color=SELECTED if is_selected else "transparent",
                corner_radius=R_CTRL)
            item.pack(fill="x", pady=(0, S_XS))
            self.file_rows[file] = item

            def on_enter(_e, row=item, path=file):
                if path != self.selected_file and not self._converting:
                    row.configure(fg_color=RAISED)

            def on_leave(_e, row=item, path=file):
                if path != self.selected_file:
                    row.configure(fg_color="transparent")

            def on_click(_e, path=file):
                self.set_selected_file(path)
                self.show_preview(path)

            # A filled square holds the thumbnail's place until it is read.
            thumb_lbl = ctk.CTkLabel(item, text="", width=THUMB, height=THUMB,
                                     fg_color=HOVER, corner_radius=R_CTRL - 2)
            thumb_lbl.pack(side="left", padx=(S_SM, 0), pady=S_SM)
            self.file_thumb_labels[file] = thumb_lbl
            self._show_thumb(thumb_lbl, file)

            # Right-hand widgets are packed before the text, so a long name
            # is clipped rather than pushing the remove button out of the row.
            remove_btn = ghost_button(item, "✕", lambda i=idx: self.remove_file(i))
            remove_btn.configure(state="disabled" if self._locked else "normal")
            remove_btn.pack(side="right", padx=(0, S_SM))
            self.file_remove_btns[file] = remove_btn
            Tooltip(self, [remove_btn], "Remove from queue  ·  Delete")

            status_lbl = ctk.CTkLabel(item, text="", width=20,
                                      font=F.body_b, text_color=FAINT)
            status_lbl.pack(side="right")
            self.file_status_labels[file] = status_lbl
            self._apply_status_style(status_lbl, self.file_status.get(file, ""))

            left = ctk.CTkFrame(item, fg_color="transparent")
            left.pack(side="left", fill="both", expand=True, padx=(S_MD, 0))

            name_lbl = ctk.CTkLabel(
                left, text=Path(file).name, font=F.body_b,
                text_color=ACCENT_TX if is_selected else TEXT, anchor="w")
            name_lbl.pack(fill="x")
            self.file_name_labels[file] = name_lbl

            meta_lbl = ctk.CTkLabel(left, text=self._format_meta(file),
                                    font=F.mono, text_color=DIM, anchor="w")
            meta_lbl.pack(fill="x")
            self.file_meta_labels[file] = meta_lbl

            for w in (item, thumb_lbl, left, name_lbl, meta_lbl, status_lbl):
                w.configure(cursor="hand2")
                w.bind("<Enter>", on_enter)
                w.bind("<Leave>", on_leave)
                w.bind("<Button-1>", on_click)
            remove_btn.bind("<Enter>", on_enter)
            remove_btn.bind("<Leave>", on_leave)

        self.after_idle(self._sync_queue_scrollbar)

    def _apply_status_style(self, label: ctk.CTkLabel, status: str):
        styles = {
            "converting": ("●", WARN),
            "done":       ("✓", OK),
            "error":      ("✕", DANGER),
        }
        text, color = styles.get(status, ("", FAINT))
        label.configure(text=text, text_color=color)

    def _update_file_status(self, path: str, status: str):
        self.file_status[path] = status
        label = self.file_status_labels.get(path)
        if label and label.winfo_exists():
            self._apply_status_style(label, status)

    def set_selected_file(self, path: str):
        previous = self.selected_file
        if previous and previous in self.file_rows:
            row = self.file_rows[previous]
            if row.winfo_exists():
                row.configure(fg_color="transparent")
            name = self.file_name_labels.get(previous)
            if name and name.winfo_exists():
                name.configure(text_color=TEXT)
        self.selected_file = path
        if path in self.file_rows:
            row = self.file_rows[path]
            if row.winfo_exists():
                row.configure(fg_color=SELECTED)
            name = self.file_name_labels.get(path)
            if name and name.winfo_exists():
                name.configure(text_color=ACCENT_TX)
        self._refresh_summary()

    def _remove_selected(self):
        if self._converting or not self.selected_file:
            return
        if self.selected_file in self.webp_files:
            self.remove_file(self.webp_files.index(self.selected_file))

    def remove_file(self, index: int):
        if self._converting:
            return
        if 0 <= index < len(self.webp_files):
            removed = self.webp_files.pop(index)
            self.file_status.pop(removed, None)
            self.file_meta.pop(removed, None)
            self.file_thumbs.pop(removed, None)
            if self.selected_file == removed:
                self.selected_file = self.webp_files[0] if self.webp_files else None
            self.update_files_list()
            if self.selected_file:
                self.show_preview(self.selected_file)
            else:
                self._clear_preview()

    def clear_file_list(self):
        if self._converting:
            return
        self.webp_files.clear()
        self.selected_file = None
        self.file_status.clear()
        self.file_meta.clear()
        self.file_thumbs.clear()
        self.update_files_list()
        self._clear_preview()

    def _clear_preview(self):
        self._stop_preview()
        self._detach_preview_image()
        self._reset_preview_frames()
        self.preview_label.configure(image=None, text="Select a file to preview")
        self.preview_info.configure(text="")
        self._set_preview_clickable(False)

    def _reset_preview_frames(self):
        self.preview_frames = []
        self.preview_bar.configure(fg_color=BG, progress_color=BG)

    def _set_preview_clickable(self, on: bool):
        """Pointer over the whole canvas only while there's a clip to toggle."""
        cursor = "hand2" if on else "arrow"
        self.preview_well.configure(cursor=cursor)
        self.preview_label.configure(cursor=cursor)

    def _detach_preview_image(self):
        """Drop the photo image from the underlying tk label while it still exists.

        CTkLabel.configure(image=None) leaves the old PhotoImage name set on the
        internal tk label; once the old frames are garbage-collected that name is
        deleted from the Tk interpreter and every later configure on the label
        raises 'image "pyimageN" doesn't exist'.
        """
        try:
            self.preview_label._label.configure(image="")
        except (AttributeError, tk.TclError):
            pass
        self.preview_label.image = None

    def open_output_folder(self):
        if not os.path.isdir(self.output_folder):
            self.show_toast("Output folder no longer exists", kind="err")
            return
        try:
            if sys.platform == "win32":
                os.startfile(self.output_folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", self.output_folder])
            else:
                subprocess.Popen(["xdg-open", self.output_folder])
        except OSError as e:
            self.show_toast(f"Could not open folder: {e}", kind="err")

    # ── Preview ──────────────────────────────

    def _preview_box(self) -> tuple:
        """Fit box for preview frames, in CTk (scaled) units."""
        well = self.preview_well
        scale = ctk.ScalingTracker.get_widget_scaling(well)
        w, h = well.winfo_width() / scale, well.winfo_height() / scale
        if w <= 1 or h <= 1:      # not laid out yet
            w, h = PREVIEW_MIN
        return max(2, int(w)), max(2, int(h))

    def _on_preview_resize(self, _event=None):
        # Debounced: a window drag fires dozens of Configure events.
        if self._resize_after_id:
            self.after_cancel(self._resize_after_id)
        self._resize_after_id = self.after(180, self._apply_preview_resize)

    def _apply_preview_resize(self):
        self._resize_after_id = None
        if self._closing or not self.selected_file:
            return
        if self._preview_box() != self._preview_fit:
            self.show_preview(self.selected_file, keep_current=True)

    def show_preview(self, filepath: str, keep_current: bool = False):
        """Load frames for filepath in the background.

        keep_current keeps the visible animation running (and its play/pause
        state) until the new frames are ready — used for resizes and theme
        switches of the same file, so they don't flash "Loading…".
        """
        self._preview_gen += 1
        gen = self._preview_gen
        box = self._preview_fit = self._preview_box()
        if not keep_current:
            self._stop_preview()
            self._detach_preview_image()
            self._reset_preview_frames()
            self.preview_label.configure(image=None, text="Loading preview…")
            self.preview_info.configure(text="")
        threading.Thread(
            target=self._load_preview_frames,
            args=(filepath, gen, box, keep_current), daemon=True,
        ).start()

    def _load_preview_frames(self, filepath: str, gen: int, box: tuple,
                             resume: bool):
        try:
            frames = []
            with Image.open(filepath) as im:
                w, h = fit_box(im.width, im.height, *box)
                checker = checkerboard((w, h))
                corners = rounded_mask((w, h), R_CTRL)
                fallback_ms = int(1000 / max(1, self.fps_value.get()))
                for i, frame_img in enumerate(ImageSequence.Iterator(im)):
                    if gen != self._preview_gen or self._closing:
                        return
                    if i >= MAX_PREVIEW_FRAMES:
                        break
                    rgba = frame_img.convert("RGBA").resize((w, h), Image.LANCZOS)
                    # info["duration"] is only populated once the frame is loaded
                    delay = int(frame_img.info.get("duration", 0) or 0) or fallback_ms
                    composed = checker.copy()
                    composed.paste(rgba, (0, 0), rgba)
                    composed.putalpha(corners)
                    frames.append(
                        (ctk.CTkImage(light_image=composed, size=(w, h)),
                         max(20, delay)))
            self._ui(self._start_preview, frames, gen, resume)
        except Exception as e:
            self._ui(self._preview_failed, gen, str(e))

    def _preview_failed(self, gen: int, message: str):
        if gen != self._preview_gen:
            return     # a newer preview superseded this one
        self._stop_preview()
        self._detach_preview_image()
        self._reset_preview_frames()
        self.preview_label.configure(image=None, text=f"Preview error: {message}")
        self.preview_info.configure(text="")
        self._set_preview_clickable(False)

    def _start_preview(self, frames: list, gen: int, resume: bool = False):
        if gen != self._preview_gen or not frames:
            return
        # A resumed preview (same file, new size or theme) keeps the frame on
        # screen and its play/pause state.
        running = self.preview_running if resume else True
        same_clip = resume and len(frames) == len(self.preview_frames)
        index = self.preview_index if same_clip else 0
        self._stop_preview()
        self.preview_frames = frames
        # Where each frame ends, as a fraction of the clip's running time.
        total, elapsed, self._preview_ends = sum(d for _, d in frames), 0, []
        for _, delay in frames:
            elapsed += delay
            self._preview_ends.append(elapsed / total)
        self.preview_bar.configure(fg_color=LINE, progress_color=DIM)
        self._show_frame(index)
        self._set_preview_clickable(True)
        self.preview_running = running
        self._update_preview_info()
        if running:
            self._animate_preview()

    def _update_preview_info(self):
        n = len(self.preview_frames)
        if not n:
            self.preview_info.configure(text="")
            return
        total = sum(d for _, d in self.preview_frames) / 1000
        state = "playing" if self.preview_running else "paused"
        suffix = f" (first {MAX_PREVIEW_FRAMES})" if n >= MAX_PREVIEW_FRAMES else ""
        self.preview_info.configure(
            text=f"{n} frames{suffix}  ·  {total:.1f}s  ·  {state}")

    def _toggle_preview(self):
        if self.preview_running:
            self._stop_preview()
        elif self.preview_frames:
            self.preview_running = True
            self._animate_preview()
        self._update_preview_info()

    def _on_space(self, event):
        # event.widget is whatever had focus (focus_get() is None when another
        # app holds OS focus). A focused control that uses Space stops the
        # event before it gets here.
        if isinstance(event.widget, (tk.Entry, tk.Text)):
            return
        self._toggle_preview()
        return "break"

    def _show_frame(self, index: int):
        """preview_index is always the frame on screen."""
        self.preview_index = index
        img = self.preview_frames[index][0]
        self.preview_label.configure(image=img, text="")
        self.preview_label.image = img
        self.preview_bar.set(self._preview_ends[index])

    def _animate_preview(self):
        """Show the current frame for its own duration, then advance."""
        if not self.preview_frames or not self.preview_running:
            return
        self._show_frame(self.preview_index)
        delay = self.preview_frames[self.preview_index][1]
        self._preview_after_id = self.after(delay, self._advance_preview)

    def _advance_preview(self):
        self._preview_after_id = None
        if self.preview_frames:
            self.preview_index = (self.preview_index + 1) % len(self.preview_frames)
            self._animate_preview()

    def _stop_preview(self):
        self.preview_running = False
        if self._preview_after_id:
            self.after_cancel(self._preview_after_id)
            self._preview_after_id = None

    # ── Conversion ───────────────────────────

    def _request_cancel(self):
        if self._converting:
            self._cancel_requested = True
            proc = self._ffmpeg_proc
            if proc:
                try:
                    proc.terminate()
                except OSError:
                    pass
            self._ui(self.progress_text.configure, text="Cancelling…")
            self._ui(self.convert_btn.configure, state="disabled",
                     text="■   Cancelling…")

    def _validated_settings(self):
        """Build settings dict for the worker; returns None if invalid."""
        if not os.path.isdir(self.output_folder):
            self.show_toast("Output folder does not exist — choose another", kind="err")
            return None
        if not os.access(self.output_folder, os.W_OK):
            self.show_toast("Output folder is not writable", kind="err")
            return None

        custom_w = custom_h = 0
        if self.resolution_preset.get() == "Custom":
            # Reported next to the field, which also takes focus — not a toast.
            bad = self._check_size_fields()
            if bad is not None:
                bad.focus_set()
                return None
            custom_w = int(self.custom_res_width.get().strip())
            custom_h = int(self.custom_res_height.get().strip())

        fmt = self.output_format.get()
        lossless = self.lossless.get() and fmt != ".gif"
        return {
            "fps":           max(1, self.fps_value.get()),
            "format":        fmt,
            "crf":           self.crf_value.get(),
            "lossless":      lossless,
            "keep_alpha":    keeps_alpha(fmt, lossless),
            "combine":       self.combine_videos.get(),
            "source_timing": self.use_source_timing.get(),
            "resolution":    self.resolution_preset.get(),
            "custom_w":      custom_w,
            "custom_h":      custom_h,
            "output_folder": self.output_folder,
            "files":         list(self.webp_files),
        }

    def start_conversion(self):
        if self._converting:
            self.show_toast("Conversion already running", kind="warn")
            return
        if not self.webp_files:
            self.show_toast("Add at least one WebP file first", kind="warn")
            return
        settings = self._validated_settings()
        if settings is None:
            return

        self._converting = True
        self._cancel_requested = False

        self.file_status.clear()
        for path in self.webp_files:
            self._update_file_status(path, "")

        self.convert_btn.configure(
            text="■   Cancel  (Esc)", command=self._request_cancel,
            fg_color=DANGER, hover_color=DANGER_HI, text_color=ON_ACCENT)
        self._apply_progress(0)
        self.progress_text.configure(text="Starting…", text_color=DIM)
        self._commit_status("Converting", WARN)
        self._set_controls_enabled(False)
        self.save_current_settings()

        threading.Thread(target=self._run_conversion, args=(settings,),
                         daemon=True).start()

    def _target_size(self, src_w: int, src_h: int, settings: dict) -> tuple:
        preset = settings["resolution"]
        if preset == "Custom":
            return make_even(settings["custom_w"], settings["custom_h"])
        if preset in RESOLUTION_MAP:
            return fit_box(src_w, src_h, *RESOLUTION_MAP[preset])
        return make_even(src_w, src_h)

    def _run_conversion(self, settings: dict):
        files         = settings["files"]
        combine       = settings["combine"]
        output_folder = settings["output_folder"]
        fmt           = settings["format"]
        failures: list[tuple[str, str]] = []
        done_count = 0

        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)
            try:
                if combine:
                    n = len(files)
                    all_frames: list[tuple[str, int]] = []
                    target: tuple | None = None
                    for idx, webp_file in enumerate(files):
                        if self._cancel_requested:
                            self._finish_cancelled()
                            return
                        self._ui(self._update_file_status, webp_file, "converting")
                        stage = f"Extracting {idx + 1}/{n}"
                        try:
                            if target is None:
                                with Image.open(webp_file) as im:
                                    target = self._target_size(im.width, im.height,
                                                               settings)
                            frames = self._extract_frames(
                                webp_file, temp_dir, settings,
                                start_idx=len(all_frames),
                                target_override=target,
                                progress=lambda p, i=idx: self._ui_progress(
                                    (i + p) / (n + 1), stage),
                            )
                            if not frames:
                                raise RuntimeError("no frames decoded")
                        except Exception as e:
                            for f in files:
                                self._ui(self._update_file_status, f, "error")
                            raise RuntimeError(
                                f"{Path(webp_file).name}: {e}") from e
                        all_frames.extend(frames)

                    if self._cancel_requested:
                        self._finish_cancelled()
                        return

                    out = unique_output_path(output_folder, "combined", fmt)
                    self._encode(all_frames, out, settings,
                                 progress=lambda p: self._ui_progress(
                                     (n + p) / (n + 1), "Encoding"))
                    if self._cancel_requested:
                        self._finish_cancelled()
                        return
                    for f in files:
                        self._ui(self._update_file_status, f, "done")
                    done_count = len(files)

                else:
                    n = len(files)
                    for idx, webp_file in enumerate(files):
                        if self._cancel_requested:
                            self._finish_cancelled()
                            return
                        self._ui(self._update_file_status, webp_file, "converting")
                        name = Path(webp_file).name
                        frames = []
                        try:
                            frames = self._extract_frames(
                                webp_file, temp_dir, settings,
                                progress=lambda p, i=idx: self._ui_progress(
                                    (2 * i + p) / (2 * n),
                                    f"Extracting {i + 1}/{n}"),
                            )
                            if self._cancel_requested:
                                self._finish_cancelled()
                                return
                            if not frames:
                                raise RuntimeError("no frames decoded")
                            out = unique_output_path(
                                output_folder, Path(webp_file).stem, fmt)
                            self._encode(frames, out, settings,
                                         progress=lambda p, i=idx: self._ui_progress(
                                             (2 * i + 1 + p) / (2 * n),
                                             f"Encoding {i + 1}/{n}"))
                            if self._cancel_requested:
                                self._finish_cancelled()
                                return
                            self._ui(self._update_file_status, webp_file, "done")
                            done_count += 1
                        except Exception as e:
                            self._ui(self._update_file_status, webp_file, "error")
                            failures.append((name, str(e)))
                        finally:
                            # free disk space before next file
                            for frame_path, _ in frames:
                                try:
                                    os.remove(frame_path)
                                except OSError:
                                    pass

                if failures:
                    first = failures[0]
                    self._ui(self.progress_text.configure,
                             text=f"{done_count} done, {len(failures)} failed")
                    self._ui(self._commit_status, "Error", DANGER)
                    self._ui(self.show_toast,
                             f"{first[0]}: {first[1][:160]}", "err", 6000)
                    if done_count:
                        self._ui(self.show_toast,
                                 f"{done_count} file(s) converted, "
                                 f"{len(failures)} failed", "warn", 6000)
                else:
                    self._ui(self._apply_progress, 1.0)
                    self._ui(self.progress_text.configure, text="All files saved")
                    self._ui(self._commit_status, "Done", OK)
                    self._ui(self.show_toast, "Conversion complete — click to open folder",
                             "ok", 5000, self.open_output_folder)

            except Exception as e:
                msg = str(e)
                self._ui(self.show_toast, f"Error: {msg[:200]}", "err", 6000)
                # The full message is in the toast; the bar only has room for this.
                self._ui(self.progress_text.configure, text="Conversion failed")
                self._ui(self._commit_status, "Error", DANGER)
                for f in files:
                    if self.file_status.get(f) == "converting":
                        self._ui(self._update_file_status, f, "error")

            finally:
                self._converting = False
                self._cancel_requested = False
                self._ui(self._reset_convert_btn)
                self._ui(self._set_controls_enabled, True)

    def _finish_cancelled(self):
        self._ui(self.progress_text.configure, text="Cancelled")
        self._ui(self._commit_status, "Cancelled", WARN)
        self._ui(self.show_toast, "Conversion cancelled", "warn")

    def _reset_convert_btn(self):
        self.convert_btn.configure(
            state="normal", command=self.start_conversion,
            fg_color=ACCENT, hover_color=ACCENT_HI, text_color=ON_ACCENT)
        self._refresh_convert_btn()

    # ── Frame extraction ─────────────────────

    def _extract_frames(self, webp_file: str, temp_dir: Path, settings: dict,
                        start_idx: int = 0, target_override: tuple | None = None,
                        progress=None) -> list[tuple[str, int]]:
        """Stream frames to PNG files. Returns [(path, duration_ms), ...].
        Raises on decode failure."""
        frames: list[tuple[str, int]] = []
        with Image.open(webp_file) as im:
            target = target_override or self._target_size(im.width, im.height,
                                                          settings)
            n_frames = getattr(im, "n_frames", None)
            for i, frame in enumerate(ImageSequence.Iterator(im)):
                if self._cancel_requested:
                    break
                img = frame.convert("RGBA")
                # info["duration"] is only populated once the frame is loaded
                duration = int(frame.info.get("duration", 0) or 0)
                if target_override:
                    img = letterbox(img, target, settings["keep_alpha"])
                elif img.size != target:
                    img = img.resize(target, Image.LANCZOS)
                path = temp_dir / f"frame_{start_idx + i:06d}.png"
                img.save(path)
                frames.append((str(path), duration))
                if progress and n_frames:
                    progress(min(1.0, (i + 1) / n_frames))
        return frames

    # ── Encoding ─────────────────────────────

    def _frame_durations_sec(self, frames: list[tuple[str, int]],
                             settings: dict) -> list[float]:
        fallback = 1.0 / settings["fps"]
        if settings["source_timing"]:
            return [(ms / 1000.0) if ms > 0 else fallback for _, ms in frames]
        return [fallback] * len(frames)

    def _encode(self, frames: list[tuple[str, int]], output_path: str,
                settings: dict, progress=None):
        try:
            if settings["format"] == ".gif":
                self._encode_gif(frames, output_path, settings, progress)
            else:
                self._encode_ffmpeg(frames, output_path, settings, progress)
        except Exception:
            self._remove_partial(output_path)
            raise
        if self._cancel_requested:
            self._remove_partial(output_path)

    @staticmethod
    def _remove_partial(path: str):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    def _encode_gif(self, frames, output_path, settings, progress=None):
        durations = self._frame_durations_sec(frames, settings)
        images = []
        try:
            for i, (path, _) in enumerate(frames):
                if self._cancel_requested:
                    return
                with Image.open(path) as img:
                    images.append(rgba_to_gif_frame(img.convert("RGBA")))
                if progress:
                    progress(0.9 * (i + 1) / len(frames))
            if not images:
                raise RuntimeError("no frames to encode")
            images[0].save(
                output_path, save_all=True, append_images=images[1:],
                duration=[max(20, int(d * 1000)) for d in durations],
                loop=0, disposal=2, transparency=255, optimize=False,
            )
            if progress:
                progress(1.0)
        finally:
            for img in images:
                img.close()

    def _encode_ffmpeg(self, frames, output_path, settings, progress=None):
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

        durations = self._frame_durations_sec(frames, settings)
        list_path = os.path.join(os.path.dirname(frames[0][0]), "_framelist.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            last_entry = ""
            for (frame_path, _), dur in zip(frames, durations):
                escaped = frame_path.replace(os.sep, "/").replace("'", "'\\''")
                last_entry = f"file '{escaped}'\n"
                f.write(last_entry)
                f.write(f"duration {dur:.6f}\n")
            # concat demuxer quirk: repeat last file so its duration is honored
            f.write(last_entry)

        cmd = [ffmpeg_exe, "-y", "-f", "concat", "-safe", "0", "-i", list_path,
               "-progress", "pipe:1", "-nostats",
               *encoder_args(settings["format"], settings["crf"],
                             settings["lossless"]),
               output_path]

        kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        # The context manager closes both pipes; without it every encode
        # leaked two handles.
        with subprocess.Popen(cmd, **kwargs) as proc:
            self._ffmpeg_proc = proc
            stderr_chunks: list[bytes] = []
            drain = threading.Thread(
                target=lambda: stderr_chunks.append(proc.stderr.read()),
                daemon=True)
            drain.start()
            try:
                total = len(frames)
                for raw in proc.stdout:
                    line = raw.decode("utf-8", errors="ignore").strip()
                    if progress and total and line.startswith("frame="):
                        try:
                            progress(min(1.0, int(line.split("=", 1)[1]) / total))
                        except ValueError:
                            pass
                proc.wait()
            finally:
                self._ffmpeg_proc = None
            drain.join(timeout=2)

        if proc.returncode != 0 and not self._cancel_requested:
            err = (stderr_chunks[0] if stderr_chunks else b"")
            raise RuntimeError(
                f"ffmpeg failed: {err.decode(errors='ignore')[-400:]}")
        if progress and not self._cancel_requested:
            progress(1.0)

    # ── Toast notifications ──────────────────

    def show_toast(self, message: str, kind: str = "info",
                   duration: int = 3200, on_click=None):
        glyphs = {
            "info": ("●", ACCENT_TX),
            "ok":   ("✓", OK),
            "warn": ("!", WARN),
            "err":  ("✕", DANGER),
        }
        glyph, color = glyphs.get(kind, glyphs["info"])

        # Toasts float over the action bar and output column (both SURFACE),
        # so the rounded corners are drawn against SURFACE, not the window.
        toast = ctk.CTkFrame(self, fg_color=RAISED, bg_color=SURFACE,
                             corner_radius=R_PANEL,
                             border_width=BORDER_W, border_color=LINE)
        icon = ctk.CTkLabel(toast, text=glyph, font=F.body_b, text_color=color)
        icon.pack(side="left", padx=(S_LG, S_MD), pady=S_MD)
        label = ctk.CTkLabel(toast, text=message, font=F.body,
                             text_color=TEXT, wraplength=340, justify="left")
        label.pack(side="left", padx=(0, S_LG), pady=S_MD)

        def dismiss(_e=None):
            self._dismiss_toast(toast)

        for w in (toast, icon, label):
            w.configure(cursor="hand2")
            if on_click:
                w.bind("<Button-1>", lambda _e: (on_click(), dismiss()))
            else:
                w.bind("<Button-1>", dismiss)

        self._toasts.append(toast)
        if len(self._toasts) > 4:
            self._dismiss_toast(self._toasts[0])
        self._place_toasts()
        self.after(duration, dismiss)

    def _dismiss_toast(self, toast):
        if toast in self._toasts:
            self._toasts.remove(toast)
        try:
            toast.destroy()
        except tk.TclError:
            pass
        self._place_toasts()

    def _place_toasts(self):
        y = -S_LG
        for toast in reversed(self._toasts):
            if not toast.winfo_exists():
                continue
            toast.place(relx=1.0, rely=1.0, anchor="se", x=-S_LG, y=y)
            y -= toast.winfo_reqheight() + S_SM

    # ── Window close ─────────────────────────

    def _on_close(self):
        if self._converting:
            if not messagebox.askyesno(
                    "Conversion running",
                    "A conversion is still running.\nCancel it and quit?"):
                return
            self._cancel_requested = True
            proc = self._ffmpeg_proc
            if proc:
                try:
                    proc.terminate()
                except OSError:
                    pass
        self._closing = True
        self._stop_preview()
        try:
            self.save_current_settings()
        except Exception:
            pass
        self.destroy()


def main():
    try:
        app = WebPConverterApp()
        app.mainloop()
    except Exception:
        import traceback
        err = traceback.format_exc()
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("WebP Converter — crashed", err[-1500:])
            root.destroy()
        except Exception:
            pass
        print(err, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
