import os
import re
import sys
import json
import threading
import tempfile
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
import customtkinter as ctk
from PIL import Image, ImageDraw, ImageSequence, ImageTk
import imageio_ffmpeg

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _HAS_DND = True
except Exception:
    _HAS_DND = False

APP_VERSION = "2.2.0"

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

RESOLUTION_MAP = {
    "480p":  (854,  480),
    "720p":  (1280, 720),
    "1080p": (1920, 1080),
    "4K":    (3840, 2160),
}

# ── Design tokens ──────────────────────────────
BG          = "#141414"
CARD        = "#1e1e1e"
CARD2       = "#242424"
BORDER      = "#2e2e2e"
ACCENT      = "#00c2d4"
ACCENT_DIM  = "#007a87"
TEXT        = "#e8e8e8"
TEXT_DIM    = "#707070"
TEXT_MUTED  = "#404040"
RED         = "#c0392b"
GREEN       = "#1a8a4a"
AMBER       = "#b07d20"
SELECT_BG   = "#0d3d47"
HOVER_BG    = "#2a2a2a"

_FONT_SANS = "Segoe UI" if sys.platform == "win32" else "SF Pro Display" if sys.platform == "darwin" else "sans-serif"
_FONT_MONO = "Consolas" if sys.platform == "win32" else "SF Mono" if sys.platform == "darwin" else "monospace"

FONT_HEAD   = (_FONT_SANS, 13, "bold")
FONT_BODY   = (_FONT_SANS, 12)
FONT_SMALL  = (_FONT_SANS, 11)
FONT_MONO   = (_FONT_MONO, 11)
FONT_TITLE  = (_FONT_SANS, 22, "bold")
FONT_LABEL  = (_FONT_SANS, 12)
FONT_BTN    = (_FONT_SANS, 13, "bold")


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


def aspect_fit(img_width, img_height, max_size=380):
    if img_width <= 0 or img_height <= 0:
        return 2, 2
    ratio = min(max_size / img_width, max_size / img_height)
    return make_even(max(2, int(img_width * ratio)), max(2, int(img_height * ratio)))


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
    img = Image.new("RGB", size, "#262626")
    draw = ImageDraw.Draw(img)
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            if (x // cell + y // cell) % 2 == 0:
                draw.rectangle([x, y, x + cell - 1, y + cell - 1], fill="#1c1c1c")
    return img


def rgba_to_gif_frame(img: Image.Image) -> Image.Image:
    """Quantize RGBA to palette frame with binary transparency at index 255."""
    alpha = img.getchannel("A")
    mask = alpha.point(lambda a: 255 if a <= 128 else 0)
    frame = img.convert("RGB").convert("P", palette=Image.Palette.ADAPTIVE, colors=255)
    frame.paste(255, mask)
    frame.info["transparency"] = 255
    return frame


# ─────────────────────────────────────────────
# Reusable section card
# ─────────────────────────────────────────────

def section_card(parent, title: str = "", **kwargs) -> ctk.CTkFrame:
    card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=10,
                        border_width=1, border_color=BORDER, **kwargs)
    if title:
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(12, 0))
        ctk.CTkLabel(header, text=title, font=FONT_HEAD,
                     text_color=ACCENT).pack(side="left")
        ctk.CTkFrame(header, height=1, fg_color=BORDER).pack(
            side="left", fill="x", expand=True, padx=(12, 0), pady=1)
    return card


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

        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
        self.configure(bg=BG)

        self.title(f"WebP → Video Converter  v{APP_VERSION}")
        self._settings = load_settings()
        geo = self._settings.get("geometry", "")
        if isinstance(geo, str) and re.fullmatch(r"\d{3,5}x\d{3,5}([+-]\d+){2}", geo):
            self.geometry(geo)
        else:
            self.geometry("1000x740")
        self.minsize(860, 600)
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

        # Settings vars
        self.output_format     = ctk.StringVar(value=".mp4")
        self.fps_value         = ctk.IntVar(value=16)
        self.combine_videos    = ctk.BooleanVar(value=False)
        self.use_source_timing = ctk.BooleanVar(value=True)
        self.resolution_preset = ctk.StringVar(value="Same Resolution")
        self.crf_value         = ctk.IntVar(value=22)

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
        self.after(100, self._force_left_render)
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
            self.dnd_bind("<<DropEnter>>", lambda _e: self._set_status("DROP FILES", ACCENT))
            self.dnd_bind("<<DropLeave>>", lambda _e: self._restore_status())
        except Exception:
            pass

    def _force_left_render(self):
        try:
            canvas = self._left_scroll._parent_canvas
            canvas.yview_scroll(1, "units")
            canvas.yview_scroll(-1, "units")
        except AttributeError:
            pass

    # ── Layout skeleton ──────────────────────

    def _build_layout(self):
        # ── Title bar ──
        title_bar = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0, height=56)
        title_bar.pack(fill="x", side="top")
        title_bar.pack_propagate(False)

        ctk.CTkLabel(
            title_bar,
            text="  ⬡  WebP → Video",
            font=FONT_TITLE,
            text_color=TEXT,
        ).pack(side="left", padx=(20, 6), pady=10)

        ctk.CTkLabel(
            title_bar, text=f"v{APP_VERSION}",
            font=FONT_MONO, text_color=TEXT_DIM,
        ).pack(side="left", pady=(18, 6))

        self.status_dot = ctk.CTkLabel(
            title_bar, text="● READY",
            font=(_FONT_MONO, 11, "bold"),
            text_color=ACCENT,
        )
        self.status_dot.pack(side="right", padx=20)
        self._status_current = ("READY", ACCENT)

        # ── Body: two columns ──
        body = ctk.CTkFrame(self, fg_color=BG)
        body.pack(fill="both", expand=True, padx=16, pady=12)
        body.columnconfigure(0, weight=1, minsize=340)
        body.columnconfigure(1, weight=1, minsize=380)
        body.rowconfigure(0, weight=1)

        left_scroll = ctk.CTkScrollableFrame(
            body, fg_color=BG,
            scrollbar_button_color=CARD2,
            scrollbar_button_hover_color=BORDER,
            corner_radius=0,
        )
        left_scroll.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._left_scroll = left_scroll

        right = ctk.CTkFrame(body, fg_color=BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        self._build_settings(left_scroll)
        self._build_preview(right)

    # ── Left: settings ───────────────────────

    def _build_settings(self, parent):
        # FILES card
        files_card = section_card(parent, "FILES")
        files_card.pack(fill="x", pady=(0, 10))

        self.add_files_btn = ctk.CTkButton(
            files_card, text="＋  Add WebP Files",
            command=self.select_webps,
            fg_color=ACCENT, hover_color=ACCENT_DIM,
            text_color="#000000", font=FONT_BTN,
            corner_radius=8, height=36,
        )
        self.add_files_btn.pack(fill="x", padx=16, pady=(10, 6))

        btn_row = ctk.CTkFrame(files_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 6))

        self.add_folder_btn = ctk.CTkButton(
            btn_row, text="🗂  Add Folder",
            command=self.select_folder_of_webps,
            fg_color=CARD2, hover_color=HOVER_BG,
            text_color=TEXT, font=FONT_BTN,
            border_width=1, border_color=BORDER,
            corner_radius=8, height=36,
        )
        self.add_folder_btn.pack(side="left", expand=True, fill="x", padx=(0, 6))

        self.output_folder_btn = ctk.CTkButton(
            btn_row, text="📁  Output Folder",
            command=self.select_output_folder,
            fg_color=CARD2, hover_color=HOVER_BG,
            text_color=TEXT, font=FONT_BTN,
            border_width=1, border_color=BORDER,
            corner_radius=8, height=36,
        )
        self.output_folder_btn.pack(side="left", expand=True, fill="x")

        self.output_folder_label = ctk.CTkLabel(
            files_card,
            text=f"→  {self.output_folder}",
            font=FONT_MONO, text_color=TEXT_DIM,
            anchor="w", wraplength=290, justify="left",
            cursor="hand2",
        )
        self.output_folder_label.pack(fill="x", padx=16, pady=(0, 12))
        self.output_folder_label.bind("<Button-1>", lambda _e: self.open_output_folder())

        # FORMAT & RESOLUTION card
        fmt_card = section_card(parent, "FORMAT  &  RESOLUTION")
        fmt_card.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(fmt_card, text="Container", font=FONT_SMALL,
                     text_color=TEXT_DIM, anchor="w").pack(fill="x", padx=16, pady=(10, 2))

        self.format_seg = ctk.CTkSegmentedButton(
            fmt_card, values=list(VALID_FORMATS),
            variable=self.output_format,
            fg_color=CARD2,
            selected_color=ACCENT, selected_hover_color=ACCENT_DIM,
            unselected_color=CARD2, unselected_hover_color=HOVER_BG,
            text_color=TEXT, font=FONT_BODY,
            corner_radius=8, height=32,
        )
        self.format_seg.pack(fill="x", padx=16)

        ctk.CTkLabel(fmt_card, text="Resolution", font=FONT_SMALL,
                     text_color=TEXT_DIM, anchor="w").pack(fill="x", padx=16, pady=(10, 2))

        self.res_menu = ctk.CTkOptionMenu(
            fmt_card,
            values=list(VALID_RESOLUTIONS),
            variable=self.resolution_preset,
            command=self.toggle_custom_res_entry,
            fg_color=CARD2, button_color=ACCENT, button_hover_color=ACCENT_DIM,
            text_color=TEXT, font=FONT_BODY, dropdown_fg_color=CARD2,
            corner_radius=8,
        )
        self.res_menu.pack(fill="x", padx=16)

        self._res_hint = ctk.CTkLabel(
            fmt_card, text="Presets keep aspect ratio (fit inside box)",
            font=FONT_SMALL, text_color=TEXT_MUTED, anchor="w",
        )
        self._res_hint.pack(fill="x", padx=16, pady=(2, 0))

        # Bottom padding for fmt_card when custom row is hidden
        self._fmt_card_pad = ctk.CTkFrame(fmt_card, fg_color="transparent", height=14)
        self._fmt_card_pad.pack(fill="x")

        # Custom resolution row (initially hidden)
        self.custom_res_row = ctk.CTkFrame(fmt_card, fg_color="transparent")

        self.custom_res_width = ctk.CTkEntry(
            self.custom_res_row, width=90, placeholder_text="Width",
            fg_color=CARD2, border_color=BORDER,
            placeholder_text_color=TEXT_DIM, text_color=TEXT, corner_radius=8,
        )
        self.custom_res_width.pack(side="left")

        ctk.CTkLabel(self.custom_res_row, text=" × ", font=FONT_BODY,
                     text_color=TEXT_DIM).pack(side="left")

        self.custom_res_height = ctk.CTkEntry(
            self.custom_res_row, width=90, placeholder_text="Height",
            fg_color=CARD2, border_color=BORDER,
            placeholder_text_color=TEXT_DIM, text_color=TEXT, corner_radius=8,
        )
        self.custom_res_height.pack(side="left")

        ctk.CTkLabel(
            self.custom_res_row, text="  px (exact, may stretch)",
            font=FONT_SMALL, text_color=TEXT_MUTED,
        ).pack(side="left")

        # ENCODING card
        enc_card = section_card(parent, "ENCODING")
        enc_card.pack(fill="x", pady=(0, 10))

        self.timing_check = ctk.CTkCheckBox(
            enc_card,
            text="Use original frame timing",
            variable=self.use_source_timing,
            command=self._on_timing_toggle,
            text_color=TEXT, font=FONT_BODY,
            checkmark_color="#000000",
            fg_color=ACCENT, hover_color=ACCENT_DIM,
            border_color=BORDER, corner_radius=4,
        )
        self.timing_check.pack(anchor="w", padx=16, pady=(12, 0))

        ctk.CTkLabel(
            enc_card, text="Keeps each frame's real duration · FPS below is fallback",
            font=FONT_SMALL, text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=16, pady=(0, 0))

        self.fps_slider = self._slider_row(
            enc_card, label="Frames Per Second", suffix="FPS",
            var=self.fps_value, from_=1, to=60, steps=59, attr="fps_label",
        )
        self.crf_slider = self._slider_row(
            enc_card, label="Compression  (CRF)", suffix="CRF",
            var=self.crf_value, from_=18, to=30, steps=12, attr="crf_label",
            hint="18 = best quality   ·   30 = smaller file",
        )

        self.combine_check = ctk.CTkCheckBox(
            enc_card,
            text="Combine all files into one output",
            variable=self.combine_videos,
            text_color=TEXT, font=FONT_BODY,
            checkmark_color="#000000",
            fg_color=ACCENT, hover_color=ACCENT_DIM,
            border_color=BORDER, corner_radius=4,
        )
        self.combine_check.pack(anchor="w", padx=16, pady=(10, 14))

        # CONVERT card
        conv_card = section_card(parent, "CONVERT")
        conv_card.pack(fill="x", pady=(0, 10))

        self.convert_btn = ctk.CTkButton(
            conv_card,
            text="▶   START CONVERSION",
            command=self.start_conversion,
            fg_color=ACCENT, hover_color=ACCENT_DIM,
            text_color="#000000",
            font=(_FONT_SANS, 15, "bold"),
            corner_radius=8, height=46,
        )
        self.convert_btn.pack(fill="x", padx=16, pady=(10, 10))

        self.progress_bar = ctk.CTkProgressBar(
            conv_card,
            fg_color=CARD2, progress_color=ACCENT,
            corner_radius=4, height=6,
        )
        self.progress_bar.pack(fill="x", padx=16, pady=(0, 6))
        self.progress_bar.set(0)

        self.progress_text = ctk.CTkLabel(
            conv_card, text="Ctrl+Enter to start", font=FONT_MONO,
            text_color=TEXT_DIM, anchor="w",
        )
        self.progress_text.pack(fill="x", padx=16, pady=(0, 14))

        self._lockable = [
            self.add_files_btn, self.add_folder_btn, self.output_folder_btn,
            self.format_seg, self.res_menu,
            self.fps_slider, self.crf_slider,
            self.timing_check, self.combine_check,
            self.custom_res_width, self.custom_res_height,
        ]

    def _slider_row(self, parent, label, suffix, var, from_, to, steps,
                    attr, hint=""):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(10, 0))

        ctk.CTkLabel(row, text=label, font=FONT_LABEL, text_color=TEXT).pack(side="left")
        val_lbl = ctk.CTkLabel(
            row, text=f"{var.get()} {suffix}",
            font=(_FONT_MONO, 12, "bold"), text_color=ACCENT,
        )
        val_lbl.pack(side="right")
        setattr(self, attr, val_lbl)

        slider = ctk.CTkSlider(
            parent, from_=from_, to=to, number_of_steps=steps, variable=var,
            fg_color=CARD2, progress_color=ACCENT,
            button_color=ACCENT, button_hover_color=ACCENT_DIM,
        )
        slider.pack(fill="x", padx=16, pady=(4, 0))
        slider.configure(
            command=lambda v, lbl=val_lbl, sfx=suffix:
                self._on_slider_change(lbl, sfx, v)
        )

        if hint:
            ctk.CTkLabel(parent, text=hint, font=FONT_SMALL,
                         text_color=TEXT_MUTED).pack(anchor="w", padx=16, pady=(2, 0))
        return slider

    def _on_slider_change(self, lbl, suffix, value):
        lbl.configure(text=f"{int(float(value))} {suffix}")
        if suffix == "FPS":
            self._refresh_meta_labels()

    def _on_timing_toggle(self):
        disabled = self.use_source_timing.get()
        self.fps_slider.configure(state="disabled" if disabled else "normal")
        self.fps_label.configure(text_color=TEXT_DIM if disabled else ACCENT)
        self._refresh_meta_labels()

    # ── Right: preview + queue ───────────────

    def _build_preview(self, parent):
        prev_card = section_card(parent, "PREVIEW")
        prev_card.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        self.preview_label = ctk.CTkLabel(
            prev_card,
            text="Select a file to preview",
            font=FONT_SMALL, text_color=TEXT_MUTED,
            width=380, height=240,
        )
        self.preview_label.pack(padx=16, pady=(10, 2))

        self.preview_info = ctk.CTkLabel(
            prev_card, text="", font=FONT_MONO, text_color=TEXT_DIM,
        )
        self.preview_info.pack(padx=16, pady=(0, 10))

        list_card = section_card(parent, "QUEUE")
        list_card.grid(row=1, column=0, sticky="nsew")

        list_btn_row = ctk.CTkFrame(list_card, fg_color="transparent")
        list_btn_row.pack(fill="x", padx=16, pady=(10, 8))

        self.clear_all_btn = ctk.CTkButton(
            list_btn_row, text="🗑  Clear All",
            command=self.clear_file_list,
            fg_color=CARD2, hover_color=HOVER_BG,
            text_color=TEXT, font=FONT_SMALL,
            border_width=1, border_color=BORDER,
            corner_radius=6, height=30, width=110,
        )
        self.clear_all_btn.pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            list_btn_row, text="📂  Open Folder",
            command=self.open_output_folder,
            fg_color=CARD2, hover_color=HOVER_BG,
            text_color=TEXT, font=FONT_SMALL,
            border_width=1, border_color=BORDER,
            corner_radius=6, height=30, width=120,
        ).pack(side="left")

        self.queue_count_label = ctk.CTkLabel(
            list_btn_row, text="",
            font=FONT_SMALL, text_color=TEXT_MUTED,
        )
        self.queue_count_label.pack(side="right")

        self.files_list_frame = ctk.CTkScrollableFrame(
            list_card, fg_color="transparent",
            scrollbar_button_color=CARD2,
            scrollbar_button_hover_color=BORDER,
        )
        self.files_list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

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
        self.output_folder_label.configure(text=f"→  {self.output_folder}")

    def _set_status(self, text: str, color: str = ACCENT):
        self.status_dot.configure(text=f"● {text}", text_color=color)

    def _commit_status(self, text: str, color: str = ACCENT):
        self._status_current = (text, color)
        self._set_status(text, color)

    def _restore_status(self):
        self._set_status(*self._status_current)

    def toggle_custom_res_entry(self, choice):
        if choice == "Custom":
            self._fmt_card_pad.pack_forget()
            self.custom_res_row.pack(fill="x", padx=16, pady=(10, 14))
        else:
            self.custom_res_row.pack_forget()
            self._fmt_card_pad.pack(fill="x")

    def _set_controls_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for widget in self._lockable:
            try:
                widget.configure(state=state)
            except (tk.TclError, ValueError):
                pass
        self.clear_all_btn.configure(state=state)
        if enabled:
            self._on_timing_toggle()

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

    def _ui_progress(self, fraction: float, stage: str = ""):
        fraction = max(0.0, min(1.0, fraction))
        pct = int(fraction * 100)
        key = (pct, stage)
        if key == getattr(self, "_last_progress", None):
            return
        self._last_progress = key
        text = f"{stage}  ·  {pct}%" if stage else f"{pct}%"
        self._ui(self.progress_bar.set, fraction)
        self._ui(self.progress_text.configure, text=text)

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
        self._restore_status()
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
            return f"{meta['size_mb']:.1f} MB  ·  unreadable file"
        fps = max(1, self.fps_value.get())
        if self.use_source_timing.get() and meta["total_ms"] > 0:
            duration = meta["total_ms"] / 1000
        else:
            duration = meta["frames"] / fps
        return (f"{meta['size_mb']:.1f} MB  ·  {meta['w']}×{meta['h']}"
                f"  ·  {meta['frames']} frames  ·  {duration:.1f}s")

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

        count = len(self.webp_files)
        self.queue_count_label.configure(
            text=f"{count} file{'s' if count != 1 else ''}" if count else "")

        if not self.webp_files:
            hint = ("Drop .webp files here\nor press Ctrl+O"
                    if _HAS_DND else "No files in queue\nCtrl+O to add")
            empty = ctk.CTkLabel(
                self.files_list_frame,
                text=hint,
                font=FONT_SMALL, text_color=TEXT_MUTED,
                cursor="hand2",
            )
            empty.pack(pady=30)
            empty.bind("<Button-1>", lambda _e: self.select_webps())
            return

        for idx, file in enumerate(self.webp_files):
            is_selected = file == self.selected_file
            bg = SELECT_BG if is_selected else CARD2
            border = ACCENT if is_selected else BORDER

            item = ctk.CTkFrame(
                self.files_list_frame, fg_color=bg, corner_radius=8,
                border_width=1, border_color=border,
            )
            item.pack(fill="x", padx=4, pady=3)
            self.file_rows[file] = item

            def on_enter(e, row=item, path=file):
                if path != self.selected_file:
                    row.configure(fg_color=HOVER_BG)

            def on_leave(e, row=item, path=file):
                if path != self.selected_file:
                    row.configure(fg_color=CARD2)

            def on_click(e, path=file):
                self.show_preview(path)
                self.set_selected_file(path)

            left = ctk.CTkFrame(item, fg_color="transparent")
            left.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=8)

            ctk.CTkLabel(
                left, text=Path(file).name,
                font=FONT_HEAD,
                text_color=ACCENT if is_selected else TEXT,
                anchor="w",
            ).pack(fill="x")

            meta_lbl = ctk.CTkLabel(
                left, text=self._format_meta(file),
                font=FONT_MONO, text_color=TEXT_DIM, anchor="w",
            )
            meta_lbl.pack(fill="x")
            self.file_meta_labels[file] = meta_lbl

            # Per-file status indicator
            status_lbl = ctk.CTkLabel(
                item, text="", width=24,
                font=(_FONT_SANS, 14, "bold"), text_color=TEXT_MUTED,
            )
            status_lbl.pack(side="right", padx=(0, 2))
            self.file_status_labels[file] = status_lbl

            status = self.file_status.get(file, "")
            if status:
                self._apply_status_style(status_lbl, status)

            remove_btn = ctk.CTkButton(
                item, text="✕", width=28, height=28,
                fg_color="transparent", hover_color=RED,
                text_color=TEXT_DIM, font=FONT_BODY,
                corner_radius=6,
                command=lambda i=idx: self.remove_file(i),
            )
            remove_btn.pack(side="right", padx=(0, 4), pady=5)

            for w in (item, left):
                w.bind("<Enter>", on_enter)
                w.bind("<Leave>", on_leave)
                w.bind("<Button-1>", on_click)
            for child in left.winfo_children():
                child.bind("<Enter>", on_enter)
                child.bind("<Leave>", on_leave)
                child.bind("<Button-1>", on_click)
            remove_btn.bind("<Enter>", on_enter)
            remove_btn.bind("<Leave>", on_leave)

    def _apply_status_style(self, label: ctk.CTkLabel, status: str):
        if status == "converting":
            label.configure(text="⟳", text_color=AMBER)
        elif status == "done":
            label.configure(text="✓", text_color=GREEN)
        elif status == "error":
            label.configure(text="✕", text_color=RED)
        else:
            label.configure(text="", text_color=TEXT_MUTED)

    def _update_file_status(self, path: str, status: str):
        self.file_status[path] = status
        label = self.file_status_labels.get(path)
        if label and label.winfo_exists():
            self._apply_status_style(label, status)

    def set_selected_file(self, path: str):
        if self.selected_file and self.selected_file in self.file_rows:
            row = self.file_rows[self.selected_file]
            if row.winfo_exists():
                row.configure(fg_color=CARD2, border_color=BORDER)
        self.selected_file = path
        if path in self.file_rows:
            row = self.file_rows[path]
            if row.winfo_exists():
                row.configure(fg_color=SELECT_BG, border_color=ACCENT)

    def _remove_selected(self):
        if self._converting or not self.selected_file:
            return
        if self.selected_file in self.webp_files:
            idx = self.webp_files.index(self.selected_file)
            self.remove_file(idx)

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
        self.preview_frames = []
        self.preview_label.configure(image=None, text="Select a file to preview",
                                     cursor="arrow")
        self.preview_label.image = None
        self.preview_info.configure(text="")

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
        self.preview_label.configure(image=None, text="Loading preview…")
        self.preview_label.image = None
        self.preview_info.configure(text="")
        threading.Thread(
            target=self._load_preview_frames, args=(filepath, gen), daemon=True
        ).start()

    def _load_preview_frames(self, filepath: str, gen: int):
        try:
            frames = []
            with Image.open(filepath) as im:
                w, h = aspect_fit(im.width, im.height, 380)
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
            self.preview_label.bind("<Button-1>", lambda _e: self._toggle_preview())

    def _update_preview_info(self):
        n = len(self.preview_frames)
        if not n:
            self.preview_info.configure(text="")
            return
        total = sum(d for _, d in self.preview_frames) / 1000
        state = "▶ playing" if self.preview_running else "▮▮ paused"
        suffix = f"  (first {MAX_PREVIEW_FRAMES})" if n >= MAX_PREVIEW_FRAMES else ""
        self.preview_info.configure(
            text=f"{n} frames{suffix}  ·  {total:.1f}s  ·  {state} — click image or Space")

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
                     text="⏹   CANCELLING…")

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
                self.show_toast("Enter numeric width and height for Custom resolution",
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
            text="⏹   CANCEL  (Esc)", command=self._request_cancel,
            fg_color=RED, hover_color="#e74c3c",
            text_color=TEXT,
        )
        self.progress_bar.set(0)
        self.progress_text.configure(text="Starting…")
        self._commit_status("CONVERTING", AMBER)
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
                    self._ui(self._commit_status, "ERROR", RED)
                    self._ui(self.show_toast,
                             f"{first[0]}: {first[1][:160]}", "err", 6000)
                    if done_count:
                        self._ui(self.show_toast,
                                 f"{done_count} file(s) converted, "
                                 f"{len(failures)} failed", "warn", 6000)
                else:
                    self._ui(self.progress_bar.set, 1.0)
                    self._ui(self.progress_text.configure,
                             text="Done — files saved to output folder")
                    self._ui(self._commit_status, "DONE", GREEN)
                    self._ui(self.show_toast, "Conversion complete — click to open folder",
                             "ok", 5000, self.open_output_folder)

            except Exception as e:
                msg = str(e)
                self._ui(self.show_toast, f"Error: {msg[:200]}", "err", 6000)
                self._ui(self.progress_text.configure, text=f"Error: {msg[:120]}")
                self._ui(self._commit_status, "ERROR", RED)
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
        self._ui(self._commit_status, "CANCELLED", AMBER)
        self._ui(self.show_toast, "Conversion cancelled", "warn")

    def _reset_convert_btn(self):
        self.convert_btn.configure(
            state="normal",
            text="▶   START CONVERSION",
            command=self.start_conversion,
            fg_color=ACCENT, hover_color=ACCENT_DIM,
            text_color="#000000",
        )

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
        colors = {
            "info": (CARD2, TEXT),
            "ok":   (GREEN, "#ffffff"),
            "warn": (AMBER, "#000000"),
            "err":  (RED, "#ffffff"),
        }
        bg, fg = colors.get(kind, colors["info"])
        toast = ctk.CTkFrame(self, fg_color=bg, corner_radius=8,
                             border_width=1, border_color=BORDER)
        label = ctk.CTkLabel(toast, text=message, font=FONT_HEAD,
                             text_color=fg, wraplength=360, justify="left")
        label.pack(padx=18, pady=10)

        def dismiss(_e=None):
            self._dismiss_toast(toast)

        for w in (toast, label):
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
        y = -16
        for toast in reversed(self._toasts):
            if not toast.winfo_exists():
                continue
            toast.place(relx=1.0, rely=1.0, anchor="se", x=-16, y=y)
            y -= toast.winfo_reqheight() + 8

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
