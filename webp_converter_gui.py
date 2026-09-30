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
from PIL import Image, ImageDraw, ImageSequence, ImageTk
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
PREVIEW_W, PREVIEW_H = 420, 190

VALID_FORMATS = (".mp4", ".mkv", ".webm", ".gif")
VALID_RESOLUTIONS = ("Same Resolution", "480p", "720p", "1080p", "4K", "Custom")
VALID_THEMES = ("dark", "light")

RESOLUTION_MAP = {
    "480p":  (854,  480),
    "720p":  (1280, 720),
    "1080p": (1920, 1080),
    "4K":    (3840, 2160),
}

# ─────────────────────────────────────────────
# Design tokens
#
# Colours are (light, dark) pairs. CustomTkinter resolves the pair against the
# current appearance mode, so switching themes is a single
# ctk.set_appearance_mode() call — no per-widget bookkeeping.
# ─────────────────────────────────────────────

BG         = ("#F4F4F6", "#0B0B0D")   # window / gutter
SURFACE    = ("#FFFFFF", "#141417")   # panels, chrome bars
RAISED     = ("#F1F1F4", "#1C1C21")   # controls, rows, wells
HOVER      = ("#E8E8EC", "#24242A")   # hover state of RAISED
LINE       = ("#E3E3E8", "#27272E")   # hairline borders

TEXT       = ("#16161A", "#ECECF0")   # primary copy
DIM        = ("#67676F", "#8D8D96")   # labels, metadata
FAINT      = ("#7E7E88", "#6E6E78")   # hints, placeholders

ACCENT     = ("#3355E8", "#4463FA")   # interactive fill; ≥4.8:1 with white
ACCENT_HI  = ("#2843C4", "#3A55E0")   # accent hover
ACCENT_TX  = ("#2843C4", "#8FA2FF")   # accent-coloured text on SURFACE
ON_ACCENT  = "#FFFFFF"

OK         = ("#137A3C", "#3DB86A")
WARN       = ("#9A6207", "#D9922B")
DANGER     = ("#C42B22", "#E85C50")
DANGER_HI  = ("#A32019", "#C4453A")

DROP_TINT  = ("#EEF1FE", "#171B2E")   # drag-over fill for the drop zone
CHECK_A    = ("#EDEDF0", "#1E1E23")   # preview transparency checkerboard
CHECK_B    = ("#E2E2E7", "#17171B")

# ── Geometry ───────────────────────────────────
# Content panels round and inset; window chrome is square and full-bleed.
# Inner gaps always exceed inner radii, so nested corners never collide.

R_PANEL  = 12
R_CTRL   = 8
R_CHECK  = 5
R_PILL   = 3

H_CTRL   = 36
H_MINI   = 30
H_CTA    = 44
H_SLIDER = 18   # track is H_SLIDER - 2*SLIDER_INSET thick
H_BAR    = 6
SLIDER_INSET = 6

S_XS, S_SM, S_MD, S_LG, S_XL = 4, 8, 12, 16, 24
PAD_X, PAD_Y = 16, 14
GAP      = 10
BORDER_W = 1

LABEL_COL = 74   # width of the form label column

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
    F.brand   = (sans, 16, "bold")
    F.section = (sans, 10, "bold")
    F.body    = (sans, 12)
    F.body_b  = (sans, 12, "bold")
    F.small   = (sans, 11)
    F.btn     = (sans, 12, "bold")
    F.cta     = (sans, 14, "bold")
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


def fit_box(w, h, box_w, box_h):
    """Largest even size fitting inside box while keeping aspect ratio."""
    if w <= 0 or h <= 0:
        return make_even(box_w, box_h)
    ratio = min(box_w / w, box_h / h)
    return make_even(max(2, round(w * ratio)), max(2, round(h * ratio)))


def letterbox(img: Image.Image, target: tuple) -> Image.Image:
    """Aspect-fit img inside target canvas, centered on opaque black."""
    if img.size == target:
        return img
    w, h = fit_box(img.width, img.height, *target)
    fitted = img.resize((w, h), Image.LANCZOS)
    canvas = Image.new("RGBA", target, (0, 0, 0, 255))
    canvas.paste(fitted, ((target[0] - w) // 2, (target[1] - h) // 2), fitted)
    return canvas


def unique_output_path(folder: str, stem: str, ext: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip() or "output"
    path = os.path.join(folder, f"{safe}{ext}")
    n = 1
    while os.path.exists(path):
        path = os.path.join(folder, f"{safe} ({n}){ext}")
        n += 1
    return path


def checkerboard(size: tuple, cell: int = 12) -> Image.Image:
    img = Image.new("RGB", size, tone(CHECK_A))
    draw = ImageDraw.Draw(img)
    dark = tone(CHECK_B)
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            if (x // cell + y // cell) % 2 == 0:
                draw.rectangle([x, y, x + cell - 1, y + cell - 1], fill=dark)
    return img


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

def panel(parent, title: str = "", pad_x: int = PAD_X):
    """A content panel. Returns (card, head, body); head is None without a title."""
    card = ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=R_PANEL,
                        border_width=BORDER_W, border_color=LINE)
    head = None
    if title:
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=PAD_X, pady=(PAD_Y, 0))
        ctk.CTkLabel(head, text=title.upper(), font=F.section,
                     text_color=DIM).pack(side="left")
    body = ctk.CTkFrame(card, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=pad_x,
              pady=(S_MD if title else PAD_Y, PAD_Y))
    return card, head, body


def primary_button(parent, text, command, height=H_CTRL, **kw):
    return ctk.CTkButton(parent, text=text, command=command,
                         fg_color=ACCENT, hover_color=ACCENT_HI,
                         text_color=ON_ACCENT, font=F.btn,
                         corner_radius=R_CTRL, height=height,
                         border_width=0, **kw)


def secondary_button(parent, text, command, height=H_CTRL, **kw):
    return ctk.CTkButton(parent, text=text, command=command,
                         fg_color=RAISED, hover_color=HOVER,
                         text_color=TEXT, font=F.btn,
                         corner_radius=R_CTRL, height=height,
                         border_width=BORDER_W, border_color=LINE, **kw)


def ghost_button(parent, text, command, size=26, **kw):
    return ctk.CTkButton(parent, text=text, command=command,
                         fg_color="transparent", hover_color=HOVER,
                         text_color=FAINT, font=F.body,
                         corner_radius=R_CTRL,
                         width=size, height=size, **kw)


def form_label(parent, text, row):
    lbl = ctk.CTkLabel(parent, text=text, font=F.body,
                       text_color=DIM, anchor="w", width=LABEL_COL)
    lbl.grid(row=row, column=0, sticky="w", pady=(0, S_SM))
    return lbl


def hint(parent, text):
    return ctk.CTkLabel(parent, text=text, font=F.small,
                        text_color=FAINT, anchor="w", justify="left")


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
        # The layout has a hard minimum height; never open taller than the display.
        avail_h = max(600, self.winfo_screenheight() - 80)
        geo = self._settings.get("geometry", "")
        if isinstance(geo, str) and re.fullmatch(r"\d{3,5}x\d{3,5}([+-]\d+){2}", geo):
            self.geometry(geo)
        else:
            self.geometry(f"1160x{min(890, avail_h)}")
        self.minsize(1040, min(865, avail_h))
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

        # Settings vars
        self.output_format     = ctk.StringVar(value=".mp4")
        self.fps_value         = ctk.IntVar(value=16)
        self.combine_videos    = ctk.BooleanVar(value=False)
        self.use_source_timing = ctk.BooleanVar(value=True)
        self.resolution_preset = ctk.StringVar(value="Same Resolution")
        self.crf_value         = ctk.IntVar(value=22)
        self._timing_mode      = ctk.StringVar(value="Original")

        # Preview state
        self.preview_frames:   list = []   # list of (CTkImage, delay_ms)
        self.preview_index     = 0
        self.preview_running   = False
        self._preview_after_id = None
        self._preview_gen      = 0

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
        self.bind("<Delete>", lambda _e: self._remove_selected())
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
        self._build_header()
        self._build_footer()

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(side="top", fill="both", expand=True, padx=S_MD, pady=S_MD)
        body.columnconfigure(0, weight=4, minsize=320)
        body.columnconfigure(1, weight=6, minsize=430)
        body.rowconfigure(0, weight=1)

        left = ctk.CTkFrame(body, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, GAP // 2))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        right = ctk.CTkFrame(body, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(GAP // 2, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1, minsize=PREVIEW_H + 80)  # preview grows
        right.rowconfigure(1, weight=0)   # settings are intrinsic height

        self._build_source(left)
        self._build_output(right)

    # ── Chrome: header ───────────────────────

    def _build_header(self):
        bar = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=58)
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)
        ctk.CTkFrame(self, height=BORDER_W, fg_color=LINE,
                     corner_radius=0).pack(side="top", fill="x")

        ctk.CTkLabel(bar, text="◆", font=F.brand,
                     text_color=ACCENT_TX).pack(side="left", padx=(S_LG, S_SM))
        ctk.CTkLabel(bar, text="WebP → Video", font=F.brand,
                     text_color=TEXT).pack(side="left")
        ctk.CTkLabel(bar, text=f"v{APP_VERSION}", font=F.mono,
                     text_color=FAINT).pack(side="left", padx=(S_MD, 0))

        self.theme_btn = ghost_button(
            bar, "☾" if self._theme == "dark" else "☀",
            self._toggle_theme, size=H_MINI)
        self.theme_btn.configure(text_color=DIM)
        self.theme_btn.pack(side="right", padx=(S_SM, S_LG))

        self.status_text = ctk.CTkLabel(bar, text="Ready", font=F.body,
                                        text_color=DIM)
        self.status_text.pack(side="right", padx=(0, S_MD))
        self.status_dot = ctk.CTkLabel(bar, text="●", font=F.small,
                                       text_color=DIM)
        self.status_dot.pack(side="right", padx=(0, S_SM))
        self._status_current = ("Ready", DIM)

    # ── Chrome: footer ───────────────────────

    def _build_footer(self):
        bar = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0)
        bar.pack(side="bottom", fill="x")
        ctk.CTkFrame(self, height=BORDER_W, fg_color=LINE,
                     corner_radius=0).pack(side="bottom", fill="x")

        row = ctk.CTkFrame(bar, fg_color="transparent")
        row.pack(fill="x", padx=S_LG, pady=(S_MD, S_SM))

        self.convert_btn = primary_button(
            row, "▶   Convert", self.start_conversion, height=H_CTA, width=190)
        self.convert_btn.pack(side="right")

        self.output_folder_btn = secondary_button(
            row, "Change", self.select_output_folder, height=H_MINI, width=76)
        self.output_folder_btn.pack(side="right", padx=(S_MD, S_MD))

        ctk.CTkLabel(row, text="Output", font=F.body,
                     text_color=DIM).pack(side="left")
        self.output_folder_label = ctk.CTkLabel(
            row, text="", font=F.mono, text_color=ACCENT_TX,
            anchor="w", cursor="hand2")
        self.output_folder_label.pack(side="left", padx=(S_MD, 0))
        self.output_folder_label.bind("<Button-1>",
                                      lambda _e: self.open_output_folder())

        self.progress_bar = ctk.CTkProgressBar(
            bar, fg_color=RAISED, progress_color=ACCENT,
            corner_radius=R_PILL, height=H_BAR)
        self.progress_bar.pack(fill="x", padx=S_LG, pady=(0, S_SM))
        self._apply_progress(0)

        self.progress_text = ctk.CTkLabel(
            bar, text="Ctrl+Enter to start", font=F.mono,
            text_color=FAINT, anchor="w")
        self.progress_text.pack(fill="x", padx=S_LG, pady=(0, S_MD))

    # ── Left column: source ──────────────────

    def _build_source(self, parent):
        card, head, body = panel(parent, "Source", pad_x=S_MD)
        card.grid(row=0, column=0, sticky="nsew")

        self.queue_count_label = ctk.CTkLabel(head, text="", font=F.mono,
                                              text_color=FAINT)
        self.queue_count_label.pack(side="right")

        # Drop zone — click adds files, drag-over tints it
        self.drop_zone = ctk.CTkFrame(
            body, fg_color=RAISED, corner_radius=R_CTRL,
            border_width=BORDER_W, border_color=LINE, height=96)
        self.drop_zone.pack(fill="x", padx=S_XS)
        self.drop_zone.pack_propagate(False)

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
                                      font=F.small, text_color=FAINT)
        self.drop_hint.pack()

        for w in (self.drop_zone, inner, self.drop_glyph,
                  self.drop_title, self.drop_hint):
            w.configure(cursor="hand2")
            w.bind("<Button-1>", lambda _e: self.select_webps())
            w.bind("<Enter>", lambda _e: self._hover_drop(True))
            w.bind("<Leave>", lambda _e: self._hover_drop(False))

        # Queue
        self.files_list_frame = ctk.CTkScrollableFrame(
            body, fg_color="transparent", corner_radius=0,
            scrollbar_button_color=LINE,
            scrollbar_button_hover_color=FAINT)
        self.files_list_frame.pack(fill="both", expand=True, pady=(S_MD, 0))

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.pack(fill="x", padx=S_XS, pady=(S_MD, 0))

        self.add_folder_btn = secondary_button(
            actions, "Add folder", self.select_folder_of_webps, height=H_MINI)
        self.add_folder_btn.pack(side="left", expand=True, fill="x",
                                 padx=(0, S_SM))

        self.clear_all_btn = secondary_button(
            actions, "Clear all", self.clear_file_list, height=H_MINI)
        self.clear_all_btn.pack(side="left", expand=True, fill="x")

    def _hover_drop(self, on: bool):
        if self._converting:
            return
        self.drop_zone.configure(border_color=ACCENT if on else LINE)

    def _set_drop_active(self, on: bool):
        self.drop_zone.configure(
            fg_color=DROP_TINT if on else RAISED,
            border_color=ACCENT if on else LINE)

    # ── Right column: preview + output ───────

    def _build_output(self, parent):
        prev_card, _, prev_body = panel(parent, "Preview")
        prev_card.grid(row=0, column=0, sticky="nsew", pady=(0, GAP))

        self.preview_label = ctk.CTkLabel(
            prev_body, text="Select a file to preview",
            font=F.small, text_color=FAINT,
            width=PREVIEW_W, height=PREVIEW_H,
            corner_radius=R_CTRL, fg_color=RAISED)
        self.preview_label.pack(expand=True)
        self.preview_label.bind("<Button-1>", lambda _e: self._toggle_preview())

        self.preview_info = ctk.CTkLabel(prev_body, text="", font=F.mono,
                                         text_color=FAINT)
        self.preview_info.pack(pady=(S_MD, 0))

        out_card, _, form = panel(parent, "Output")
        out_card.grid(row=1, column=0, sticky="nsew")
        form.columnconfigure(0, weight=0, minsize=LABEL_COL)
        form.columnconfigure(1, weight=1)

        # Format
        form_label(form, "Format", 0)
        self.format_seg = ctk.CTkSegmentedButton(
            form, values=list(VALID_FORMATS), variable=self.output_format,
            fg_color=RAISED, selected_color=ACCENT,
            selected_hover_color=ACCENT_HI,
            unselected_color=RAISED, unselected_hover_color=HOVER,
            text_color=TEXT, font=F.body,
            corner_radius=R_CTRL, height=H_CTRL, border_width=2)
        self.format_seg.grid(row=0, column=1, sticky="ew", pady=(0, S_SM))

        # Size
        form_label(form, "Size", 1)
        self.res_menu = ctk.CTkOptionMenu(
            form, values=list(VALID_RESOLUTIONS),
            variable=self.resolution_preset, command=self.toggle_custom_res_entry,
            fg_color=RAISED, button_color=RAISED, button_hover_color=HOVER,
            text_color=TEXT, font=F.body,
            dropdown_fg_color=SURFACE, dropdown_hover_color=HOVER,
            dropdown_text_color=TEXT, dropdown_font=F.body,
            corner_radius=R_CTRL, height=H_CTRL)
        self.res_menu.grid(row=1, column=1, sticky="ew", pady=(0, S_SM))

        self.custom_res_row = ctk.CTkFrame(form, fg_color="transparent")
        self.custom_res_width = ctk.CTkEntry(
            self.custom_res_row, width=84, placeholder_text="Width",
            fg_color=RAISED, border_color=LINE, border_width=BORDER_W,
            placeholder_text_color=FAINT, text_color=TEXT,
            font=F.body, corner_radius=R_CTRL, height=H_MINI)
        self.custom_res_width.pack(side="left")
        ctk.CTkLabel(self.custom_res_row, text="×", font=F.body,
                     text_color=FAINT).pack(side="left", padx=S_SM)
        self.custom_res_height = ctk.CTkEntry(
            self.custom_res_row, width=84, placeholder_text="Height",
            fg_color=RAISED, border_color=LINE, border_width=BORDER_W,
            placeholder_text_color=FAINT, text_color=TEXT,
            font=F.body, corner_radius=R_CTRL, height=H_MINI)
        self.custom_res_height.pack(side="left")
        hint(self.custom_res_row, "px — exact, may stretch").pack(
            side="left", padx=(S_MD, 0))

        # Quality
        form_label(form, "Quality", 3)
        self.crf_slider = self._slider_row(
            form, row=3, var=self.crf_value, from_=18, to=30, steps=12,
            suffix="CRF", attr="crf_label")
        hint(form, "18 lossless-ish  ·  30 smallest file").grid(
            row=4, column=1, sticky="w", pady=(0, S_MD))

        # Timing
        form_label(form, "Timing", 5)
        self.timing_seg = ctk.CTkSegmentedButton(
            form, values=["Original", "Fixed FPS"], variable=self._timing_mode,
            command=self._on_timing_mode,
            fg_color=RAISED, selected_color=ACCENT,
            selected_hover_color=ACCENT_HI,
            unselected_color=RAISED, unselected_hover_color=HOVER,
            text_color=TEXT, font=F.body,
            corner_radius=R_CTRL, height=H_CTRL, border_width=2)
        self.timing_seg.grid(row=5, column=1, sticky="ew", pady=(0, S_SM))

        form_label(form, "Rate", 6)
        self.fps_slider = self._slider_row(
            form, row=6, var=self.fps_value, from_=1, to=60, steps=59,
            suffix="FPS", attr="fps_label", pady=(0, S_MD))

        # Combine
        self.combine_check = ctk.CTkCheckBox(
            form, text="Combine all files into a single output",
            variable=self.combine_videos,
            text_color=TEXT, font=F.body,
            checkmark_color=ON_ACCENT, fg_color=ACCENT, hover_color=ACCENT_HI,
            border_color=LINE, border_width=BORDER_W,
            corner_radius=R_CHECK,
            checkbox_width=18, checkbox_height=18)
        self.combine_check.grid(row=8, column=0, columnspan=2, sticky="w")

        self._lockable = [
            self.add_folder_btn, self.clear_all_btn, self.output_folder_btn,
            self.format_seg, self.res_menu, self.timing_seg,
            self.fps_slider, self.crf_slider, self.combine_check,
            self.custom_res_width, self.custom_res_height,
        ]

    def _slider_row(self, parent, row, var, from_, to, steps, suffix, attr,
                    pady=(0, S_SM)):
        holder = ctk.CTkFrame(parent, fg_color="transparent")
        holder.grid(row=row, column=1, sticky="ew", pady=pady)

        val_lbl = ctk.CTkLabel(holder, text=f"{var.get()} {suffix}",
                               font=F.mono_b, text_color=ACCENT_TX,
                               width=62, anchor="e")
        val_lbl.pack(side="right")
        setattr(self, attr, val_lbl)

        slider = ctk.CTkSlider(
            holder, from_=from_, to=to, number_of_steps=steps, variable=var,
            fg_color=LINE, progress_color=ACCENT,
            button_color=ACCENT, button_hover_color=ACCENT_HI,
            corner_radius=R_PILL,
            height=H_SLIDER, border_width=SLIDER_INSET)
        slider.pack(side="left", fill="x", expand=True, padx=(0, S_MD))
        slider.configure(
            command=lambda v, lbl=val_lbl, sfx=suffix:
                self._on_slider_change(lbl, sfx, v))
        return slider

    def _on_slider_change(self, lbl, suffix, value):
        lbl.configure(text=f"{int(float(value))} {suffix}")
        if suffix == "FPS":
            self._refresh_meta_labels()

    def _on_timing_mode(self, choice):
        self.use_source_timing.set(choice == "Original")
        self._on_timing_toggle()

    @staticmethod
    def _style_slider(slider, label, enabled: bool):
        """State and colour move together — a disabled slider must not read as live."""
        slider.configure(state="normal" if enabled else "disabled",
                         progress_color=ACCENT if enabled else LINE,
                         button_color=ACCENT if enabled else FAINT)
        label.configure(text_color=ACCENT_TX if enabled else FAINT)

    def _on_timing_toggle(self):
        self._style_slider(self.fps_slider, self.fps_label,
                           not self.use_source_timing.get())
        self._refresh_meta_labels()

    # ── Theme ────────────────────────────────

    def _toggle_theme(self):
        self._theme = "light" if self._theme == "dark" else "dark"
        ctk.set_appearance_mode(self._theme)
        self.theme_btn.configure(text="☾" if self._theme == "dark" else "☀")
        # The preview checkerboard is a baked PIL image — rebuild it.
        if self.selected_file:
            self.show_preview(self.selected_file)
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
        self._on_timing_toggle()

    # ── UI helpers ───────────────────────────

    def _refresh_output_label(self):
        self.output_folder_label.configure(text=short_path(self.output_folder))

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
            self.custom_res_row.grid(row=2, column=1, sticky="w", pady=(0, S_SM))
        else:
            self.custom_res_row.grid_remove()

    def _set_controls_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for widget in self._lockable:
            try:
                widget.configure(state=state)
            except (tk.TclError, ValueError):
                pass
        self.drop_zone.configure(
            border_color=LINE,
            fg_color=RAISED if enabled else SURFACE)
        for slider, label in ((self.crf_slider, self.crf_label),
                              (self.fps_slider, self.fps_label)):
            self._style_slider(slider, label, enabled)
        if enabled:
            self._on_timing_toggle()   # re-mutes the rate slider if timing is Original

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
        """At zero the rounded cap would still paint a stray dot — hide the fill."""
        self.progress_bar.set(fraction)
        self.progress_bar.configure(
            progress_color=RAISED if fraction <= 0 else ACCENT)

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
        meta = {"size_mb": 0.0, "frames": 0, "w": 0, "h": 0, "total_ms": 0}
        try:
            meta["size_mb"] = os.path.getsize(path) / (1024 * 1024)
        except OSError:
            pass
        try:
            with Image.open(path) as im:
                meta["w"], meta["h"] = im.width, im.height
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
        self.file_meta[path] = meta
        label = self.file_meta_labels.get(path)
        if label and label.winfo_exists():
            label.configure(text=self._format_meta(path))

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
        return (f"{meta['size_mb']:.1f} MB  ·  {meta['w']}×{meta['h']}"
                f"  ·  {meta['frames']}f  ·  {duration:.1f}s")

    def _refresh_meta_labels(self):
        for path, label in self.file_meta_labels.items():
            if label.winfo_exists():
                label.configure(text=self._format_meta(path))

    # ── File list UI ─────────────────────────

    def update_files_list(self):
        for widget in self.files_list_frame.winfo_children():
            widget.destroy()
        self.file_rows = {}
        self.file_status_labels = {}
        self.file_meta_labels = {}
        self.file_name_labels = {}

        count = len(self.webp_files)
        self.queue_count_label.configure(text=str(count) if count else "")
        self._refresh_convert_btn()

        if not self.webp_files:
            ctk.CTkLabel(
                self.files_list_frame,
                text="Queue is empty",
                font=F.small, text_color=FAINT,
            ).pack(pady=S_XL)
            return

        for idx, file in enumerate(self.webp_files):
            is_selected = file == self.selected_file

            item = ctk.CTkFrame(
                self.files_list_frame, fg_color=RAISED, corner_radius=R_CTRL,
                border_width=BORDER_W,
                border_color=ACCENT if is_selected else LINE)
            item.pack(fill="x", pady=(0, S_SM))
            self.file_rows[file] = item

            def on_enter(_e, row=item, path=file):
                if path != self.selected_file and not self._converting:
                    row.configure(fg_color=HOVER)

            def on_leave(_e, row=item, path=file):
                if path != self.selected_file:
                    row.configure(fg_color=RAISED)

            def on_click(_e, path=file):
                self.set_selected_file(path)
                self.show_preview(path)

            left = ctk.CTkFrame(item, fg_color="transparent")
            left.pack(side="left", fill="both", expand=True,
                      padx=(S_MD, 0), pady=S_SM)

            name_lbl = ctk.CTkLabel(
                left, text=Path(file).name, font=F.body_b,
                text_color=ACCENT_TX if is_selected else TEXT, anchor="w")
            name_lbl.pack(fill="x")
            self.file_name_labels[file] = name_lbl

            meta_lbl = ctk.CTkLabel(left, text=self._format_meta(file),
                                    font=F.mono, text_color=DIM, anchor="w")
            meta_lbl.pack(fill="x")
            self.file_meta_labels[file] = meta_lbl

            remove_btn = ghost_button(item, "✕", lambda i=idx: self.remove_file(i))
            remove_btn.pack(side="right", padx=(0, S_SM))

            status_lbl = ctk.CTkLabel(item, text="", width=20,
                                      font=F.body_b, text_color=FAINT)
            status_lbl.pack(side="right")
            self.file_status_labels[file] = status_lbl
            self._apply_status_style(status_lbl, self.file_status.get(file, ""))

            for w in (item, left, name_lbl, meta_lbl, status_lbl):
                w.configure(cursor="hand2")
                w.bind("<Enter>", on_enter)
                w.bind("<Leave>", on_leave)
                w.bind("<Button-1>", on_click)
            remove_btn.bind("<Enter>", on_enter)
            remove_btn.bind("<Leave>", on_leave)

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
                row.configure(fg_color=RAISED, border_color=LINE)
            name = self.file_name_labels.get(previous)
            if name and name.winfo_exists():
                name.configure(text_color=TEXT)
        self.selected_file = path
        if path in self.file_rows:
            row = self.file_rows[path]
            if row.winfo_exists():
                row.configure(fg_color=RAISED, border_color=ACCENT)
            name = self.file_name_labels.get(path)
            if name and name.winfo_exists():
                name.configure(text_color=ACCENT_TX)

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
        self.update_files_list()
        self._clear_preview()

    def _clear_preview(self):
        self._stop_preview()
        self._detach_preview_image()
        self.preview_frames = []
        self.preview_label.configure(image=None, text="Select a file to preview",
                                     cursor="arrow")
        self.preview_info.configure(text="")

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

    def show_preview(self, filepath: str):
        self._stop_preview()
        self._preview_gen += 1
        gen = self._preview_gen
        self._detach_preview_image()
        self.preview_frames = []
        self.preview_label.configure(image=None, text="Loading preview…")
        self.preview_info.configure(text="")
        threading.Thread(
            target=self._load_preview_frames, args=(filepath, gen), daemon=True
        ).start()

    def _load_preview_frames(self, filepath: str, gen: int):
        try:
            frames = []
            with Image.open(filepath) as im:
                w, h = fit_box(im.width, im.height, PREVIEW_W, PREVIEW_H)
                checker = checkerboard((w, h))
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
                    frames.append(
                        (ctk.CTkImage(light_image=composed, size=(w, h)),
                         max(20, delay)))
            self._ui(self._start_preview, frames, gen)
        except Exception as e:
            self._ui(self.preview_label.configure,
                     image=None, text=f"Preview error: {e}")

    def _start_preview(self, frames: list, gen: int):
        if gen != self._preview_gen:
            return
        self.preview_frames = frames
        self.preview_index  = 0
        if frames:
            img = frames[0][0]
            self.preview_label.configure(image=img, text="", cursor="hand2")
            self.preview_label.image = img
            self.preview_running = True
            self._update_preview_info()
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
            text=f"{n} frames{suffix}  ·  {total:.1f}s  ·  {state} — click or Space")

    def _toggle_preview(self):
        if self.preview_running:
            self._stop_preview()
        elif self.preview_frames:
            self.preview_running = True
            self._animate_preview()
        self._update_preview_info()

    def _on_space(self, event):
        widget = self.focus_get()
        if isinstance(widget, (tk.Entry, tk.Text)):
            return
        self._toggle_preview()
        return "break"

    def _animate_preview(self):
        if not self.preview_frames or not self.preview_running:
            return
        img, delay = self.preview_frames[self.preview_index]
        self.preview_label.configure(image=img, text="")
        self.preview_label.image = img
        self.preview_index = (self.preview_index + 1) % len(self.preview_frames)
        self._preview_after_id = self.after(delay, self._animate_preview)

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
            w_str = self.custom_res_width.get().strip()
            h_str = self.custom_res_height.get().strip()
            if not (w_str.isdigit() and h_str.isdigit()):
                self.show_toast("Enter numeric width and height for Custom size",
                                kind="err")
                return None
            custom_w, custom_h = int(w_str), int(h_str)
            if not (2 <= custom_w <= MAX_DIMENSION and 2 <= custom_h <= MAX_DIMENSION):
                self.show_toast(f"Custom size must be 2–{MAX_DIMENSION} px", kind="err")
                return None

        return {
            "fps":           max(1, self.fps_value.get()),
            "format":        self.output_format.get(),
            "crf":           self.crf_value.get(),
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
                    self._ui(self.progress_text.configure,
                             text="Done — files saved to the output folder")
                    self._ui(self._commit_status, "Done", OK)
                    self._ui(self.show_toast, "Conversion complete — click to open folder",
                             "ok", 5000, self.open_output_folder)

            except Exception as e:
                msg = str(e)
                self._ui(self.show_toast, f"Error: {msg[:200]}", "err", 6000)
                self._ui(self.progress_text.configure, text=f"Error: {msg[:120]}")
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
                    img = letterbox(img, target)
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
        fmt = settings["format"]
        crf = settings["crf"]
        codec = {
            ".mp4":  "libx264",
            ".mkv":  "libx264",
            ".webm": "libvpx-vp9",
        }.get(fmt, "libx264")

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
               "-progress", "pipe:1", "-nostats", "-c:v", codec]
        if codec == "libvpx-vp9":
            cmd += ["-crf", str(crf), "-b:v", "0", "-row-mt", "1",
                    "-deadline", "good", "-cpu-used", "2",
                    "-pix_fmt", "yuv420p"]
        else:
            cmd += ["-crf", str(crf), "-pix_fmt", "yuv420p",
                    "-preset", "medium"]
            if fmt == ".mp4":
                cmd += ["-movflags", "+faststart"]
        cmd.append(output_path)

        kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        proc = subprocess.Popen(cmd, **kwargs)
        self._ffmpeg_proc = proc
        stderr_chunks: list[bytes] = []
        drain = threading.Thread(
            target=lambda: stderr_chunks.append(proc.stderr.read()), daemon=True)
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

        toast = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=R_PANEL,
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
