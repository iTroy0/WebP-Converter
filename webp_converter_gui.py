import os
import sys
import uuid
import json
import threading
import tempfile
import subprocess
from pathlib import Path
from tkinter import filedialog
import customtkinter as ctk
from PIL import Image, ImageSequence
import imageio_ffmpeg

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
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_settings(data):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except IOError:
        pass


def make_even(w: int, h: int) -> tuple:
    return w if w % 2 == 0 else w + 1, h if h % 2 == 0 else h + 1


def aspect_fit(img_width, img_height, max_size=380):
    ratio = min(max_size / img_width, max_size / img_height)
    return make_even(max(2, int(img_width * ratio)), max(2, int(img_height * ratio)))


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

class WebPConverterApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
        self.configure(bg=BG)

        self.title("WebP → Video Converter")
        self.geometry("1000x740")
        self.minsize(860, 600)
        self.resizable(True, True)

        icon_path = resource_path("app_icon.ico")
        if os.path.exists(icon_path):
            self.iconbitmap(icon_path)

        # State
        self.webp_files:    list[str] = []
        self.selected_file: str | None = None
        self.file_rows:     dict[str, ctk.CTkFrame] = {}
        self.output_folder  = os.getcwd()
        self._converting    = False
        self._cancel_requested = False
        self._ffmpeg_proc   = None

        # Per-file conversion status: path -> "" | "converting" | "done" | "error"
        self.file_status:        dict[str, str] = {}
        self.file_status_labels: dict[str, ctk.CTkLabel] = {}

        # Settings vars
        self.output_format     = ctk.StringVar(value=".mp4")
        self.fps_value         = ctk.IntVar(value=16)
        self.combine_videos    = ctk.BooleanVar(value=False)
        self.resolution_preset = ctk.StringVar(value="Same Resolution")
        self.crf_value         = ctk.IntVar(value=22)

        # Preview state
        self.preview_frames:   list[ctk.CTkImage] = []
        self.preview_index     = 0
        self.preview_running   = False
        self._preview_after_id = None

        self._build_layout()
        self.load_previous_settings()
        self.after(100, self._force_left_render)

        # Keyboard shortcuts
        self.bind("<Control-o>", lambda _e: self.select_webps())
        self.bind("<Delete>", lambda _e: self._remove_selected())
        self.bind("<Escape>", lambda _e: self._request_cancel())

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
        ).pack(side="left", padx=20, pady=10)

        self.status_dot = ctk.CTkLabel(
            title_bar, text="● READY",
            font=(_FONT_MONO, 11, "bold"),
            text_color=ACCENT,
        )
        self.status_dot.pack(side="right", padx=20)

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

        btn_row = ctk.CTkFrame(files_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(10, 6))

        self.add_files_btn = ctk.CTkButton(
            btn_row, text="＋  Add WebP Files",
            command=self.select_webps,
            fg_color=ACCENT, hover_color=ACCENT_DIM,
            text_color="#000000", font=FONT_BTN,
            corner_radius=8, height=36,
        )
        self.add_files_btn.pack(side="left", expand=True, fill="x", padx=(0, 6))

        ctk.CTkButton(
            btn_row, text="📁  Output Folder",
            command=self.select_output_folder,
            fg_color=CARD2, hover_color=HOVER_BG,
            text_color=TEXT, font=FONT_BTN,
            border_width=1, border_color=BORDER,
            corner_radius=8, height=36,
        ).pack(side="left", expand=True, fill="x")

        self.output_folder_label = ctk.CTkLabel(
            files_card,
            text=f"→  {self.output_folder}",
            font=FONT_MONO, text_color=TEXT_DIM,
            anchor="w", wraplength=290,
        )
        self.output_folder_label.pack(fill="x", padx=16, pady=(0, 12))

        # FORMAT & RESOLUTION card
        fmt_card = section_card(parent, "FORMAT  &  RESOLUTION")
        fmt_card.pack(fill="x", pady=(0, 10))

        fmt_grid = ctk.CTkFrame(fmt_card, fg_color="transparent")
        fmt_grid.pack(fill="x", padx=16, pady=(10, 0))
        fmt_grid.columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(fmt_grid, text="Container", font=FONT_SMALL,
                     text_color=TEXT_DIM).grid(row=0, column=0, sticky="w", pady=(0, 4))
        ctk.CTkLabel(fmt_grid, text="Resolution", font=FONT_SMALL,
                     text_color=TEXT_DIM).grid(row=0, column=1, sticky="w",
                                               pady=(0, 4), padx=(8, 0))

        ctk.CTkOptionMenu(
            fmt_grid, values=list(VALID_FORMATS),
            variable=self.output_format,
            fg_color=CARD2, button_color=ACCENT, button_hover_color=ACCENT_DIM,
            text_color=TEXT, font=FONT_BODY, dropdown_fg_color=CARD2,
            corner_radius=8,
        ).grid(row=1, column=0, sticky="ew")

        ctk.CTkOptionMenu(
            fmt_grid,
            values=list(VALID_RESOLUTIONS),
            variable=self.resolution_preset,
            command=self.toggle_custom_res_entry,
            fg_color=CARD2, button_color=ACCENT, button_hover_color=ACCENT_DIM,
            text_color=TEXT, font=FONT_BODY, dropdown_fg_color=CARD2,
            corner_radius=8,
        ).grid(row=1, column=1, sticky="ew", padx=(8, 0))

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
            self.custom_res_row, text="  px",
            font=FONT_SMALL, text_color=TEXT_MUTED,
        ).pack(side="left")

        # ENCODING card
        enc_card = section_card(parent, "ENCODING")
        enc_card.pack(fill="x", pady=(0, 10))

        self._slider_row(
            enc_card, label="Frames Per Second", suffix="FPS",
            var=self.fps_value, from_=1, to=60, steps=59, attr="fps_label",
        )
        self._slider_row(
            enc_card, label="Compression  (CRF)", suffix="CRF",
            var=self.crf_value, from_=18, to=30, steps=12, attr="crf_label",
            hint="18 = best quality   ·   30 = smaller file",
        )

        ctk.CTkCheckBox(
            enc_card,
            text="Combine all files into one output",
            variable=self.combine_videos,
            text_color=TEXT, font=FONT_BODY,
            checkmark_color="#000000",
            fg_color=ACCENT, hover_color=ACCENT_DIM,
            border_color=BORDER, corner_radius=4,
        ).pack(anchor="w", padx=16, pady=(4, 14))

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
            conv_card, text="", font=FONT_MONO,
            text_color=TEXT_DIM, anchor="w",
        )
        self.progress_text.pack(fill="x", padx=16, pady=(0, 14))

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
                lbl.configure(text=f"{int(float(v))} {sfx}")
        )

        if hint:
            ctk.CTkLabel(parent, text=hint, font=FONT_SMALL,
                         text_color=TEXT_MUTED).pack(anchor="w", padx=16, pady=(2, 0))

    # ── Right: preview + queue ───────────────

    def _build_preview(self, parent):
        prev_card = section_card(parent, "PREVIEW")
        prev_card.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        self.preview_label = ctk.CTkLabel(
            prev_card,
            text="No file selected",
            font=FONT_SMALL, text_color=TEXT_MUTED,
            width=380, height=240,
        )
        self.preview_label.pack(padx=16, pady=(10, 12))

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
            "output_folder": self.output_folder,
        })

    def load_previous_settings(self):
        s = load_settings()
        if not s:
            return
        fps = s.get("fps", 16)
        self.fps_value.set(max(1, min(60, int(fps))) if isinstance(fps, (int, float)) else 16)
        fmt = s.get("format", ".mp4")
        self.output_format.set(fmt if fmt in VALID_FORMATS else ".mp4")
        crf = s.get("crf", 22)
        self.crf_value.set(max(18, min(30, int(crf))) if isinstance(crf, (int, float)) else 22)
        res = s.get("resolution", "Same Resolution")
        self.resolution_preset.set(res if res in VALID_RESOLUTIONS else "Same Resolution")
        folder = s.get("output_folder", os.getcwd())
        self.output_folder = folder if isinstance(folder, str) and os.path.isdir(folder) else os.getcwd()
        self._refresh_output_label()
        self.fps_label.configure(text=f"{self.fps_value.get()} FPS")
        self.crf_label.configure(text=f"{self.crf_value.get()} CRF")
        self.toggle_custom_res_entry(self.resolution_preset.get())

    # ── UI helpers ───────────────────────────

    def _refresh_output_label(self):
        self.output_folder_label.configure(text=f"→  {self.output_folder}")

    def _set_status(self, text: str, color: str = ACCENT):
        self.status_dot.configure(text=f"● {text}", text_color=color)

    def toggle_custom_res_entry(self, choice):
        if choice == "Custom":
            self._fmt_card_pad.pack_forget()
            self.custom_res_row.pack(fill="x", padx=16, pady=(10, 14))
        else:
            self.custom_res_width.delete(0, "end")
            self.custom_res_height.delete(0, "end")
            self.custom_res_row.pack_forget()
            self._fmt_card_pad.pack(fill="x")

    def _set_controls_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.add_files_btn.configure(state=state)
        self.clear_all_btn.configure(state=state)

    # ── File selection ───────────────────────

    def select_webps(self):
        if self._converting:
            return
        files = filedialog.askopenfilenames(filetypes=[("WebP files", "*.webp")])
        if not files:
            return
        existing = set(self.webp_files)
        added = [f for f in files if f not in existing]
        self.webp_files.extend(added)
        self.update_files_list()
        if added:
            self.set_selected_file(added[0])
            self.show_preview(added[0])

    def select_output_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_folder = folder
            self._refresh_output_label()
            self.save_current_settings()

    # ── File list UI ─────────────────────────

    def update_files_list(self):
        for widget in self.files_list_frame.winfo_children():
            widget.destroy()
        self.file_rows = {}
        self.file_status_labels = {}

        count = len(self.webp_files)
        self.queue_count_label.configure(
            text=f"{count} file{'s' if count != 1 else ''}" if count else "")

        if not self.webp_files:
            empty = ctk.CTkLabel(
                self.files_list_frame,
                text="No files in queue\nCtrl+O to add",
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

            file_path    = Path(file)
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            try:
                with Image.open(file_path) as im:
                    frame_count = sum(1 for _ in ImageSequence.Iterator(im))
                    dims = f"{im.width}×{im.height}"
            except Exception:
                frame_count, dims = 0, "?"
            fps          = self.fps_value.get()
            duration_sec = frame_count / fps if fps else 0

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
                left, text=file_path.name,
                font=FONT_HEAD,
                text_color=ACCENT if is_selected else TEXT,
                anchor="w",
            ).pack(fill="x")

            ctk.CTkLabel(
                left,
                text=f"{file_size_mb:.1f} MB  ·  {dims}  ·  {frame_count} frames  ·  {duration_sec:.1f}s",
                font=FONT_MONO, text_color=TEXT_DIM, anchor="w",
            ).pack(fill="x")

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
            self.file_rows[self.selected_file].configure(
                fg_color=CARD2, border_color=BORDER)
        self.selected_file = path
        if path in self.file_rows:
            self.file_rows[path].configure(
                fg_color=SELECT_BG, border_color=ACCENT)

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
            if self.selected_file == removed:
                self.selected_file = self.webp_files[0] if self.webp_files else None
            self.update_files_list()
            if self.selected_file:
                self.show_preview(self.selected_file)
            else:
                self._stop_preview()
                self.preview_label.configure(image="", text="No file selected")

    def clear_file_list(self):
        if self._converting:
            return
        self.webp_files.clear()
        self.selected_file = None
        self.file_status.clear()
        self.update_files_list()
        self._stop_preview()
        self.preview_label.configure(image="", text="No file selected")

    def open_output_folder(self):
        if os.path.exists(self.output_folder):
            if sys.platform == "win32":
                os.startfile(self.output_folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", self.output_folder])
            else:
                subprocess.Popen(["xdg-open", self.output_folder])

    # ── Preview ──────────────────────────────

    def show_preview(self, filepath: str):
        self._stop_preview()
        self.preview_label.configure(image="", text="Loading preview…")
        threading.Thread(
            target=self._load_preview_frames, args=(filepath,), daemon=True
        ).start()

    def _load_preview_frames(self, filepath: str):
        try:
            frames: list[ctk.CTkImage] = []
            with Image.open(filepath) as im:
                w, h = aspect_fit(im.width, im.height, 380)
                for i, frame_img in enumerate(ImageSequence.Iterator(im)):
                    if i >= MAX_PREVIEW_FRAMES:
                        break
                    rgba = frame_img.convert("RGBA")
                    frames.append(ctk.CTkImage(
                        light_image=rgba.resize((w, h), Image.LANCZOS), size=(w, h)))
            self.after(0, self._start_preview, frames)
        except Exception as e:
            self.after(0, lambda: self.preview_label.configure(
                image="", text=f"Preview error: {e}"))

    def _start_preview(self, frames: list):
        self.preview_frames = frames
        self.preview_index  = 0
        if frames:
            self.preview_label.configure(image=frames[0], text="", cursor="hand2")
            self.preview_label.image = frames[0]
            self.preview_running = True
            self._animate_preview()
            self.preview_label.bind("<Button-1>", lambda _e: self._toggle_preview())

    def _toggle_preview(self):
        if self.preview_running:
            self._stop_preview()
        elif self.preview_frames:
            self.preview_running = True
            self._animate_preview()

    def _animate_preview(self):
        if not self.preview_frames or not self.preview_running:
            return
        frame = self.preview_frames[self.preview_index]
        self.preview_label.configure(image=frame, text="")
        self.preview_label.image = frame
        self.preview_index = (self.preview_index + 1) % len(self.preview_frames)
        self._preview_after_id = self.after(100, self._animate_preview)

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
                proc.terminate()
            self._ui(self.progress_text.configure, text="Cancelling…")
            self._ui(self.convert_btn.configure, state="disabled",
                     text="⏹   CANCELLING…")

    def start_conversion(self):
        if self._converting:
            self.show_toast("⏳  Conversion already running", bg=AMBER)
            return
        if not self.webp_files:
            self.show_toast("⚠️  Please add at least one WebP file", bg=RED)
            return
        if self.combine_videos.get() and self.output_format.get() == ".gif":
            self.show_toast("⚠️  Cannot combine files into a GIF", bg=RED)
            return

        self._converting = True
        self._cancel_requested = False

        # Clear old statuses
        self.file_status.clear()
        for path in self.webp_files:
            self._update_file_status(path, "")

        # Switch button to cancel
        self.convert_btn.configure(
            text="⏹   CANCEL", command=self._request_cancel,
            fg_color=RED, hover_color="#e74c3c",
            text_color=TEXT,
        )
        self.progress_bar.set(0)
        self.progress_text.configure(text="Starting…")
        self._set_status("CONVERTING", AMBER)
        self._set_controls_enabled(False)
        self.save_current_settings()

        settings = {
            "fps":        self.fps_value.get(),
            "format":     self.output_format.get(),
            "crf":        self.crf_value.get(),
            "combine":    self.combine_videos.get(),
            "resolution": self.resolution_preset.get(),
            "custom_w":   self.custom_res_width.get(),
            "custom_h":   self.custom_res_height.get(),
            "output_folder": self.output_folder,
            "files":      list(self.webp_files),
        }
        threading.Thread(target=self._run_conversion, args=(settings,),
                         daemon=True).start()

    def _run_conversion(self, settings: dict):
        fps           = settings["fps"]
        format_choice = settings["format"]
        files         = settings["files"]
        combine       = settings["combine"]
        output_folder = settings["output_folder"]

        with tempfile.TemporaryDirectory() as tmp:
            temp_dir     = Path(tmp)
            total_steps  = len(files) + 1 if combine else len(files) * 2
            current_step = 0

            try:
                if combine:
                    all_frames: list[str] = []
                    target_size: tuple | None = None
                    for idx, webp_file in enumerate(files, 1):
                        if self._cancel_requested:
                            self._finish_cancelled()
                            return

                        self.after(0, self._update_file_status,
                                   webp_file, "converting")
                        self._ui(self.progress_text.configure,
                                 text=f"Extracting {idx} / {len(files)}")
                        extracted = self._extract_frames(
                            webp_file, temp_dir, settings,
                            start_idx=len(all_frames))
                        if extracted and target_size is None:
                            with Image.open(extracted[0]) as im:
                                target_size = make_even(im.width, im.height)
                        all_frames.extend(extracted)
                        current_step += 1
                        self._ui_progress(current_step / total_steps)

                    if self._cancel_requested:
                        self._finish_cancelled()
                        return

                    if all_frames and target_size:
                        mismatched = False
                        for fpath in all_frames:
                            with Image.open(fpath) as im:
                                if make_even(im.width, im.height) != target_size:
                                    mismatched = True
                                    break

                        if mismatched:
                            self.after(0, lambda: self.show_toast(
                                f"⚠️  Mixed resolutions — resizing all to {target_size[0]}×{target_size[1]}",
                                duration=4000, bg=AMBER,
                            ))
                            self._ui(self.progress_text.configure,
                                     text=f"Normalizing to {target_size[0]}×{target_size[1]}…")
                            for fpath in all_frames:
                                if self._cancel_requested:
                                    self._finish_cancelled()
                                    return
                                with Image.open(fpath) as im:
                                    if (im.width, im.height) != target_size:
                                        im.resize(target_size, Image.LANCZOS).save(fpath)

                    if all_frames:
                        out = os.path.join(
                            output_folder,
                            f"combined_{uuid.uuid4().hex[:6]}{format_choice}",
                        )
                        self._ui(self.progress_text.configure,
                                 text="Encoding combined video…")
                        self._convert_to_video(all_frames, fps, out,
                                               format_choice, settings["crf"])
                        self._ui_progress(1.0)

                    for f in files:
                        self.after(0, self._update_file_status, f, "done")

                else:
                    for idx, webp_file in enumerate(files, 1):
                        if self._cancel_requested:
                            self._finish_cancelled()
                            return

                        self.after(0, self._update_file_status,
                                   webp_file, "converting")
                        self._ui(self.progress_text.configure,
                                 text=f"Extracting {idx} / {len(files)}")
                        frames = self._extract_frames(webp_file, temp_dir,
                                                      settings)
                        current_step += 1
                        self._ui_progress(current_step / total_steps)

                        if frames:
                            out = os.path.join(
                                output_folder,
                                f"{Path(webp_file).stem}_{uuid.uuid4().hex[:6]}{format_choice}",
                            )
                            self._ui(self.progress_text.configure,
                                     text=f"Encoding {idx} / {len(files)}")
                            self._convert_to_video(frames, fps, out,
                                                   format_choice, settings["crf"])
                        current_step += 1
                        self._ui_progress(current_step / total_steps)
                        self.after(0, self._update_file_status,
                                   webp_file, "done")

                self._ui(self.progress_text.configure,
                         text="Done — files saved to output folder")
                self._ui(self.progress_bar.set, 1.0)
                self.after(0, lambda: self._set_status("DONE", ACCENT))
                self.after(0, lambda: self.show_toast(
                    "✅  Conversion complete!", bg=GREEN))

            except Exception as e:
                self.after(0, lambda: self.show_toast(f"❌  Error: {e}", bg=RED))
                self._ui(self.progress_text.configure, text=f"Error: {e}")
                self.after(0, lambda: self._set_status("ERROR", RED))
                for f in files:
                    if self.file_status.get(f) == "converting":
                        self.after(0, self._update_file_status, f, "error")

            finally:
                self._converting = False
                self._cancel_requested = False
                self._ui(self._reset_convert_btn)
                self.after(0, lambda: self._set_controls_enabled(True))

    def _finish_cancelled(self):
        self._ui(self.progress_text.configure, text="Cancelled")
        self.after(0, lambda: self._set_status("CANCELLED", AMBER))
        self.after(0, lambda: self.show_toast("Conversion cancelled", bg=AMBER))

    def _reset_convert_btn(self):
        self.convert_btn.configure(
            state="normal",
            text="▶   START CONVERSION",
            command=self.start_conversion,
            fg_color=ACCENT, hover_color=ACCENT_DIM,
            text_color="#000000",
        )

    def _ui(self, fn, *args, **kwargs):
        self.after(0, lambda: fn(*args, **kwargs))

    def _ui_progress(self, fraction: float):
        self.after(0, lambda f=fraction: (
            self.progress_bar.set(f),
            self.progress_text.configure(text=f"{int(f * 100)}%"),
        ))

    # ── Frame extraction / saving ────────────

    def _extract_frames(self, webp_file: str, temp_dir: Path,
                        settings: dict, start_idx: int = 0) -> list[str]:
        frames: list[str] = []
        try:
            raw_frames = []
            with Image.open(webp_file) as im:
                for frame in ImageSequence.Iterator(im):
                    raw_frames.append(frame.copy())

            for i, raw_frame in enumerate(raw_frames):
                if self._cancel_requested:
                    return frames
                path = temp_dir / f"frame_{start_idx + i:06d}.png"
                self._save_frame(raw_frame, path, settings)
                frames.append(str(path))
        except Exception as e:
            print(f"Error extracting frames from {webp_file}: {e}")
        return frames

    def _save_frame(self, frame: Image.Image, path: Path, settings: dict):
        try:
            preset = settings["resolution"]
            if preset == "Custom":
                w_str = settings["custom_w"]
                h_str = settings["custom_h"]
                if w_str.isdigit() and h_str.isdigit():
                    w = max(2, min(int(w_str), MAX_DIMENSION))
                    h = max(2, min(int(h_str), MAX_DIMENSION))
                    frame = frame.resize(make_even(w, h), Image.LANCZOS)
            elif preset != "Same Resolution":
                target = RESOLUTION_MAP.get(preset)
                if target:
                    frame = frame.resize(make_even(*target), Image.LANCZOS)
            else:
                frame = frame.resize(make_even(frame.width, frame.height), Image.LANCZOS)
            frame.convert("RGBA").save(path)
        except Exception as e:
            print(f"Error saving frame {path}: {e}")

    # ── Video encoding ───────────────────────

    def _convert_to_video(self, frames: list[str], fps: int,
                          output_path: str, fmt: str, crf: int):
        if fmt == ".gif":
            images = []
            try:
                for f in frames:
                    if self._cancel_requested:
                        return
                    img = Image.open(f)
                    images.append(img.convert("RGBA"))
                    img.close()
                if not self._cancel_requested and images:
                    images[0].save(
                        output_path, save_all=True, append_images=images[1:],
                        duration=int(1000 / fps), loop=0, optimize=True,
                        disposal=2,
                    )
            except Exception as e:
                print(f"Error creating GIF: {e}")
                raise
            finally:
                for img in images:
                    img.close()
        else:
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            codec = {
                ".mp4":  "libx264",
                ".mkv":  "libx264",
                ".webm": "libvpx-vp9",
            }.get(fmt, "libx264")

            list_path = os.path.join(os.path.dirname(frames[0]),
                                     "_framelist.txt")
            frame_dur = f"{1 / fps:.6f}"
            with open(list_path, "w") as f:
                for frame_path in frames:
                    f.write(f"file '{frame_path.replace(os.sep, '/')}'\n")
                    f.write(f"duration {frame_dur}\n")

            cmd = [ffmpeg_exe, "-y", "-f", "concat", "-safe", "0",
                   "-i", list_path, "-c:v", codec]
            if codec == "libvpx-vp9":
                cmd += ["-crf", str(crf), "-b:v", "0",
                        "-pix_fmt", "yuv420p"]
            else:
                cmd += ["-crf", str(crf), "-pix_fmt", "yuv420p",
                        "-preset", "medium"]
            cmd.append(output_path)

            kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            self._ffmpeg_proc = subprocess.Popen(cmd, **kwargs)
            try:
                _, stderr = self._ffmpeg_proc.communicate()
                if self._ffmpeg_proc.returncode != 0 \
                        and not self._cancel_requested:
                    err = stderr.decode(errors="ignore")[-500:]
                    raise RuntimeError(f"ffmpeg failed:\n{err}")
            finally:
                self._ffmpeg_proc = None

    # ── Toast notification ───────────────────

    def show_toast(self, message: str, duration: int = 2800, bg: str = CARD2):
        toast = ctk.CTkToplevel(self)
        toast.overrideredirect(True)
        toast.configure(fg_color=bg)
        toast.wm_attributes("-topmost", True)
        ctk.CTkLabel(
            toast, text=message,
            font=FONT_HEAD, text_color="white",
        ).pack(padx=22, pady=12)
        x = self.winfo_x() + self.winfo_width()  - 330
        y = self.winfo_y() + self.winfo_height() - 80
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = max(0, min(x, screen_w - 320))
        y = max(0, min(y, screen_h - 60))
        toast.geometry(f"310x46+{x}+{y}")
        self.after(duration, toast.destroy)


if __name__ == "__main__":
    app = WebPConverterApp()
    app.mainloop()
