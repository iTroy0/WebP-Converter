import os
import sys
import uuid
import json
import threading
import tempfile
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog
import customtkinter as ctk
from PIL import Image, ImageSequence
from moviepy import ImageSequenceClip

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


SETTINGS_FILE = "settings.json"

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

FONT_HEAD   = ("Segoe UI", 13, "bold")
FONT_BODY   = ("Segoe UI", 12)
FONT_SMALL  = ("Segoe UI", 11)
FONT_MONO   = ("Consolas", 11)
FONT_TITLE  = ("Segoe UI", 22, "bold")
FONT_LABEL  = ("Segoe UI", 12)
FONT_BTN    = ("Segoe UI", 13, "bold")


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


def aspect_fit(img_width, img_height, max_size=380):
    ratio = min(max_size / img_width, max_size / img_height)
    w = max(2, int(img_width  * ratio))
    h = max(2, int(img_height * ratio))
    return w if w % 2 == 0 else w + 1, h if h % 2 == 0 else h + 1


def make_even(w: int, h: int) -> tuple:
    return w if w % 2 == 0 else w + 1, h if h % 2 == 0 else h + 1


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
        # Force CTkScrollableFrame to render its children correctly on first show
        self.after(100, self._force_left_render)

    def _force_left_render(self):
        """Nudge the left CTkScrollableFrame so it renders children without needing a manual scroll."""
        self._left_scroll._parent_canvas.yview_scroll(1, "units")
        self._left_scroll._parent_canvas.yview_scroll(-1, "units")

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
            font=("Consolas", 11, "bold"),
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

        ctk.CTkButton(
            btn_row, text="＋  Add WebP Files",
            command=self.select_webps,
            fg_color=ACCENT, hover_color=ACCENT_DIM,
            text_color="#000000", font=FONT_BTN,
            corner_radius=8, height=36,
        ).pack(side="left", expand=True, fill="x", padx=(0, 6))

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
            fmt_grid, values=[".mp4", ".mkv", ".webm", ".gif"],
            variable=self.output_format,
            fg_color=CARD2, button_color=ACCENT, button_hover_color=ACCENT_DIM,
            text_color=TEXT, font=FONT_BODY, dropdown_fg_color=CARD2,
            corner_radius=8,
        ).grid(row=1, column=0, sticky="ew")

        ctk.CTkOptionMenu(
            fmt_grid,
            values=["Same Resolution", "480p", "720p", "1080p", "4K", "Custom"],
            variable=self.resolution_preset,
            command=self.toggle_custom_res_entry,
            fg_color=CARD2, button_color=ACCENT, button_hover_color=ACCENT_DIM,
            text_color=TEXT, font=FONT_BODY, dropdown_fg_color=CARD2,
            corner_radius=8,
        ).grid(row=1, column=1, sticky="ew", padx=(8, 0))

        custom_row = ctk.CTkFrame(fmt_card, fg_color="transparent")
        custom_row.pack(fill="x", padx=16, pady=(10, 14))

        self.custom_res_width = ctk.CTkEntry(
            custom_row, width=90, placeholder_text="Width",
            state="disabled", fg_color=CARD2, border_color=BORDER,
            placeholder_text_color=TEXT_MUTED, text_color=TEXT, corner_radius=8,
        )
        self.custom_res_width.pack(side="left")

        ctk.CTkLabel(custom_row, text=" × ", font=FONT_BODY,
                     text_color=TEXT_DIM).pack(side="left")

        self.custom_res_height = ctk.CTkEntry(
            custom_row, width=90, placeholder_text="Height",
            state="disabled", fg_color=CARD2, border_color=BORDER,
            placeholder_text_color=TEXT_MUTED, text_color=TEXT, corner_radius=8,
        )
        self.custom_res_height.pack(side="left")

        ctk.CTkLabel(
            custom_row, text="  px (Custom only)",
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
            font=("Segoe UI", 15, "bold"),
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
            font=("Consolas", 12, "bold"), text_color=ACCENT,
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

        ctk.CTkButton(
            list_btn_row, text="🗑  Clear All",
            command=self.clear_file_list,
            fg_color=CARD2, hover_color=HOVER_BG,
            text_color=TEXT, font=FONT_SMALL,
            border_width=1, border_color=BORDER,
            corner_radius=6, height=30, width=110,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            list_btn_row, text="📂  Open Folder",
            command=self.open_output_folder,
            fg_color=CARD2, hover_color=HOVER_BG,
            text_color=TEXT, font=FONT_SMALL,
            border_width=1, border_color=BORDER,
            corner_radius=6, height=30, width=120,
        ).pack(side="left")

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
        self.fps_value.set(s.get("fps", 16))
        self.output_format.set(s.get("format", ".mp4"))
        self.crf_value.set(s.get("crf", 22))
        self.resolution_preset.set(s.get("resolution", "Same Resolution"))
        self.output_folder = s.get("output_folder", os.getcwd())
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
            self.custom_res_width.configure(
                state="normal", fg_color=CARD2, placeholder_text_color=TEXT_DIM)
            self.custom_res_height.configure(
                state="normal", fg_color=CARD2, placeholder_text_color=TEXT_DIM)
        else:
            self.custom_res_width.delete(0, "end")
            self.custom_res_height.delete(0, "end")
            self.custom_res_width.configure(
                state="disabled", fg_color=CARD2, placeholder_text_color=TEXT_MUTED)
            self.custom_res_height.configure(
                state="disabled", fg_color=CARD2, placeholder_text_color=TEXT_MUTED)

    # ── File selection ───────────────────────

    def select_webps(self):
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

        if not self.webp_files:
            ctk.CTkLabel(
                self.files_list_frame,
                text="No files added yet",
                font=FONT_SMALL, text_color=TEXT_MUTED,
            ).pack(pady=20)
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

            remove_btn = ctk.CTkButton(
                item, text="✕", width=28, height=28,
                fg_color="transparent", hover_color=RED,
                text_color=TEXT_DIM, font=("Segoe UI", 12),
                corner_radius=6,
                command=lambda i=idx: self.remove_file(i),
            )
            remove_btn.pack(side="right", padx=(0, 8), pady=5)

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

    def set_selected_file(self, path: str):
        if self.selected_file and self.selected_file in self.file_rows:
            self.file_rows[self.selected_file].configure(
                fg_color=CARD2, border_color=BORDER)
        self.selected_file = path
        if path in self.file_rows:
            self.file_rows[path].configure(
                fg_color=SELECT_BG, border_color=ACCENT)

    def remove_file(self, index: int):
        if 0 <= index < len(self.webp_files):
            removed = self.webp_files.pop(index)
            if self.selected_file == removed:
                self.selected_file = self.webp_files[0] if self.webp_files else None
            self.update_files_list()
            if self.selected_file:
                self.show_preview(self.selected_file)
            else:
                self._stop_preview()
                self.preview_label.configure(image="", text="No file selected")

    def clear_file_list(self):
        self.webp_files.clear()
        self.selected_file = None
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
                base = im.convert("RGBA")
                frames.append(ctk.CTkImage(
                    light_image=base.copy().resize((w, h), Image.LANCZOS), size=(w, h)))
                try:
                    while True:
                        im.seek(im.tell() + 1)
                        frame = im.convert("RGBA")
                        composed = Image.alpha_composite(base, frame)
                        base = composed
                        frames.append(ctk.CTkImage(
                            light_image=composed.resize((w, h), Image.LANCZOS), size=(w, h)))
                except EOFError:
                    pass
            self.after(0, self._start_preview, frames)
        except Exception as e:
            self.after(0, lambda: self.preview_label.configure(
                image="", text=f"Preview error: {e}"))

    def _start_preview(self, frames: list):
        self.preview_frames = frames
        self.preview_index  = 0
        if frames:
            self.preview_label.configure(image=frames[0], text="")
            self.preview_label.image = frames[0]
            self.preview_running = True
            self._animate_preview()
            self.preview_label.bind("<Enter>", lambda _e: self._stop_preview())
            self.preview_label.bind("<Leave>", lambda _e: self._resume_preview())

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

    def _resume_preview(self):
        if not self.preview_running and self.preview_frames:
            self.preview_running = True
            self._animate_preview()

    # ── Conversion ───────────────────────────

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
        self.convert_btn.configure(state="disabled", text="⏳  CONVERTING…",
                                   fg_color=ACCENT_DIM)
        self.progress_bar.set(0)
        self.progress_text.configure(text="Starting…")
        self._set_status("CONVERTING", AMBER)
        self.save_current_settings()
        threading.Thread(target=self._run_conversion, daemon=True).start()

    def _run_conversion(self):
        fps           = self.fps_value.get()
        format_choice = self.output_format.get()

        with tempfile.TemporaryDirectory() as tmp:
            temp_dir     = Path(tmp)
            total_steps  = len(self.webp_files) * 2
            current_step = 0

            try:
                if self.combine_videos.get():
                    all_frames: list[str] = []
                    target_size: tuple | None = None
                    for idx, webp_file in enumerate(self.webp_files, 1):
                        self._ui(self.progress_text.configure,
                                 text=f"Extracting {idx} / {len(self.webp_files)}")
                        extracted = self._extract_frames(
                            webp_file, temp_dir, start_idx=len(all_frames))
                        if extracted and target_size is None:
                            with Image.open(extracted[0]) as im:
                                target_size = make_even(im.width, im.height)
                        all_frames.extend(extracted)
                        current_step += 1
                        self._ui_progress(current_step / total_steps)

                    # Check for mismatched sizes and warn before normalizing
                    if all_frames and target_size:
                        mismatched = []
                        for fpath in all_frames:
                            with Image.open(fpath) as im:
                                if make_even(im.width, im.height) != target_size:
                                    mismatched.append(fpath)
                                    break  # one hit is enough to know

                        if mismatched:
                            self.after(0, lambda: self.show_toast(
                                f"⚠️  Mixed resolutions — resizing all to {target_size[0]}×{target_size[1]}",
                                duration=4000, bg=AMBER,
                            ))
                            self._ui(self.progress_text.configure,
                                     text=f"Normalizing to {target_size[0]}×{target_size[1]}…")
                            for fpath in all_frames:
                                with Image.open(fpath) as im:
                                    if (im.width, im.height) != target_size:
                                        im.resize(target_size, Image.LANCZOS).save(fpath)

                    if all_frames:
                        out = os.path.join(
                            self.output_folder,
                            f"combined_{uuid.uuid4().hex[:6]}{format_choice}",
                        )
                        self._ui(self.progress_text.configure,
                                 text="Encoding combined video…")
                        self._convert_to_video(all_frames, fps, out, format_choice)
                        self._ui_progress(1.0)
                else:
                    for idx, webp_file in enumerate(self.webp_files, 1):
                        self._ui(self.progress_text.configure,
                                 text=f"Extracting {idx} / {len(self.webp_files)}")
                        frames = self._extract_frames(webp_file, temp_dir)
                        current_step += 1
                        self._ui_progress(current_step / total_steps)

                        if frames:
                            out = os.path.join(
                                self.output_folder,
                                f"{Path(webp_file).stem}_{uuid.uuid4().hex[:6]}{format_choice}",
                            )
                            self._ui(self.progress_text.configure,
                                     text=f"Encoding {idx} / {len(self.webp_files)}")
                            self._convert_to_video(frames, fps, out, format_choice)
                        current_step += 1
                        self._ui_progress(current_step / total_steps)

                self._ui(self.progress_text.configure,
                         text="Done — files saved to output folder")
                self._ui(self.progress_bar.set, 1.0)
                self.after(0, lambda: self._set_status("DONE", ACCENT))
                self.after(0, lambda: self.show_toast("✅  Conversion complete!", bg=GREEN))

            except Exception as e:
                self.after(0, lambda: self.show_toast(f"❌  Error: {e}", bg=RED))
                self._ui(self.progress_text.configure, text=f"Error: {e}")
                self.after(0, lambda: self._set_status("ERROR", RED))

            finally:
                self._converting = False
                self._ui(self.convert_btn.configure,
                         state="normal",
                         text="▶   START CONVERSION",
                         fg_color=ACCENT)

    def _ui(self, fn, *args, **kwargs):
        self.after(0, lambda: fn(*args, **kwargs))

    def _ui_progress(self, fraction: float):
        self.after(0, lambda f=fraction: (
            self.progress_bar.set(f),
            self.progress_text.configure(text=f"{int(f * 100)}%"),
        ))

    # ── Frame extraction / saving ────────────

    def _extract_frames(self, webp_file: str, temp_dir: Path,
                        start_idx: int = 0) -> list[str]:
        frames: list[str] = []
        try:
            raw_frames = []
            with Image.open(webp_file) as im:
                for frame in ImageSequence.Iterator(im):
                    raw_frames.append(frame.copy())

            paths = [
                temp_dir / f"frame_{start_idx + i:06d}.png"
                for i in range(len(raw_frames))
            ]
            with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
                executor.map(self._save_frame, raw_frames, paths)
            frames = [str(p) for p in paths]
        except Exception as e:
            print(f"Error extracting frames from {webp_file}: {e}")
        return frames

    def _save_frame(self, frame: Image.Image, path: Path):
        try:
            preset = self.resolution_preset.get()
            if preset == "Custom":
                w = self.custom_res_width.get()
                h = self.custom_res_height.get()
                if w.isdigit() and h.isdigit():
                    frame = frame.resize(make_even(int(w), int(h)), Image.LANCZOS)
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
                          output_path: str, fmt: str):
        if fmt == ".gif":
            try:
                images = [Image.open(f).convert("RGBA") for f in frames]
                images[0].save(
                    output_path, save_all=True, append_images=images[1:],
                    duration=int(1000 / fps), loop=0, optimize=True, disposal=2,
                )
            except Exception as e:
                print(f"Error creating GIF: {e}")
                raise
        else:
            try:
                codec = {
                    ".mp4":  "libx264",
                    ".mkv":  "libx264",
                    ".webm": "libvpx-vp9",
                }.get(fmt, "libx264")
                clip = ImageSequenceClip(frames, fps=fps)
                clip.write_videofile(
                    output_path, codec=codec, audio=False, preset="medium",
                    ffmpeg_params=["-crf", str(self.crf_value.get()),
                                   "-pix_fmt", "yuv420p"],
                    logger=None,
                )
                clip.close()
            except Exception as e:
                print(f"Error creating video: {e}")
                raise

    # ── Toast notification ───────────────────

    def show_toast(self, message: str, duration: int = 2800, bg: str = CARD2):
        toast = ctk.CTkToplevel(self)
        toast.overrideredirect(True)
        toast.configure(fg_color=bg)
        toast.wm_attributes("-topmost", True)
        ctk.CTkLabel(
            toast, text=message,
            font=("Segoe UI", 13, "bold"), text_color="white",
        ).pack(padx=22, pady=12)
        x = self.winfo_x() + self.winfo_width()  - 330
        y = self.winfo_y() + self.winfo_height() - 80
        toast.geometry(f"310x46+{x}+{y}")
        self.after(duration, toast.destroy)


if __name__ == "__main__":
    app = WebPConverterApp()
    app.mainloop()
