import os
import sys
import uuid
import json
import threading
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox
import customtkinter as ctk
from PIL import Image, ImageSequence, ImageTk
from moviepy import ImageSequenceClip

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

SETTINGS_FILE = "settings.json"

RESOLUTION_MAP = {
    "480p": (854, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "4K": (3840, 2160)
}

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_settings(data):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f)

class WebPConverterApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
        self.configure(bg="#212121")

        self.title("WebP to Video Converter")
        self.geometry("750x650")
        self.minsize(700, 500)
        self.resizable(True, True)

        self.icon_path = resource_path("app_icon.ico")
        if os.path.exists(self.icon_path):
            self.iconbitmap(self.icon_path)

        self.webp_files = []
        self.selected_file = None
        self.file_rows = {}
        self.output_folder = os.getcwd()
        self.output_format = ctk.StringVar(value=".mp4")
        self.fps_value = ctk.IntVar(value=16)
        self.combine_videos = ctk.BooleanVar(value=False)
        self.resolution_preset = ctk.StringVar(value="Same Resolution")
        self.crf_value = ctk.IntVar(value=22)

        self.preview_frames = []
        self.preview_index = 0
        self.preview_running = False

        self.scrollable_frame = ctk.CTkScrollableFrame(
            self,
            scrollbar_button_color="#3a3a3a",
            scrollbar_button_hover_color="#505050",
            fg_color="#212121",
            corner_radius=10
        )
        self.scrollable_frame.pack(fill="both", expand=True, padx=20, pady=20)

        self.create_widgets()
        self.load_previous_settings()

    def create_widgets(self):
        title_frame = ctk.CTkFrame(self.scrollable_frame)
        title_frame.pack(pady=10)
        ctk.CTkLabel(title_frame, text="WebP to Video Converter", font=("Arial", 28, "bold")).pack()

        settings_frame = ctk.CTkFrame(self.scrollable_frame)
        settings_frame.pack(fill="x", pady=15)

        file_buttons_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        file_buttons_frame.pack(pady=10)

        ctk.CTkButton(file_buttons_frame, text="Choose WebP File(s)", command=self.select_webps).pack(side="left", padx=10)
        ctk.CTkButton(file_buttons_frame, text="Select Output Folder", command=self.select_output_folder).pack(side="left", padx=10)

        format_res_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        format_res_frame.pack(pady=10)

        format_label = ctk.CTkLabel(format_res_frame, text="Format:", font=("Arial", 14))
        format_label.pack(side="left", padx=(0, 10))
        format_menu = ctk.CTkOptionMenu(format_res_frame, values=[".mp4", ".mkv", ".webm", ".gif"], variable=self.output_format)
        format_menu.pack(side="left", padx=(0, 30))

        res_label = ctk.CTkLabel(format_res_frame, text="Resolution:", font=("Arial", 14))
        res_label.pack(side="left", padx=(0, 10))
        res_menu = ctk.CTkOptionMenu(format_res_frame, values=["Same Resolution", "480p", "720p", "1080p", "4K"], variable=self.resolution_preset)
        res_menu.pack(side="left")

        ctk.CTkLabel(settings_frame, text="Frames Per Second (FPS):", font=("Arial", 16)).pack(pady=(0, 5))
        ctk.CTkLabel(settings_frame, text="Range: 1 to 60", font=("Arial", 14)).pack(pady=(0, 5))
        fps_slider = ctk.CTkSlider(settings_frame, from_=1, to=60, number_of_steps=59, variable=self.fps_value)
        fps_slider.pack(pady=0, padx=50, fill="x")
        self.fps_label = ctk.CTkLabel(settings_frame, text=f"FPS: {self.fps_value.get()}", font=("Arial", 14))
        self.fps_label.pack(pady=(0, 5))
        def update_fps_label(value):
            self.fps_label.configure(text=f"FPS: {int(float(value))}")

        fps_slider.configure(command=update_fps_label)
        
        ctk.CTkLabel(settings_frame, text="Compression Quality (CRF):", font=("Arial", 16)).pack(pady=(1, 5))
        ctk.CTkLabel(settings_frame, text="Range: 18 (best quality) to 30 (smaller size)", font=("Arial", 14)).pack(pady=(0, 5))
        crf_slider = ctk.CTkSlider(settings_frame, from_=18, to=30, number_of_steps=12, variable=self.crf_value)
        crf_slider.pack(pady=5, padx=50, fill="x")
        self.crf_value_label = ctk.CTkLabel(settings_frame, text=f"CRF: {self.crf_value.get()}", font=("Arial", 14))
        self.crf_value_label.pack(pady=(0, 5))

        def update_crf_label(value):
            self.crf_value_label.configure(text=f"CRF: {int(float(value))}")

        crf_slider.configure(command=update_crf_label)
        ctk.CTkCheckBox(settings_frame, text="Combine all videos into one", variable=self.combine_videos).pack(pady=(1, 5))
        progress_frame = ctk.CTkFrame(self.scrollable_frame)
        progress_frame.pack(fill="x", pady=20)

        ctk.CTkButton(progress_frame, text="Start Conversion", command=self.start_conversion_thread, font=("Arial", 18)).pack(pady=10)

        self.progress_bar = ctk.CTkProgressBar(progress_frame)
        self.progress_bar.pack(pady=(0, 5), fill="x", padx=40)
        self.progress_bar.set(0)

        self.progress_text = ctk.CTkLabel(progress_frame, text="0%", font=("Arial", 14))
        self.progress_text.pack(pady=0)

        self.frame_counter = ctk.CTkLabel(progress_frame, text="Frames extracted: 0", font=("Arial", 14))
        self.frame_counter.pack(pady=(0, 10))

        preview_frame = ctk.CTkFrame(self.scrollable_frame)
        preview_frame.pack(fill="both", expand=True, pady=10)

        ctk.CTkLabel(preview_frame, text="Preview Selected Files:", font=("Arial", 16)).pack(pady=(0, 10))
        self.preview_label = ctk.CTkLabel(preview_frame, text="No preview")
        self.preview_label.pack(pady=(0, 10))
        preview_button_frame = ctk.CTkFrame(preview_frame, fg_color="transparent")
        preview_button_frame.pack(pady=(10, 0))

        ctk.CTkButton(preview_button_frame, text="Clear List", command=self.clear_file_list).pack(side="left", padx=10)
        ctk.CTkButton(preview_button_frame, text="Open Output Folder", command=self.open_output_folder).pack(side="left", padx=10)
        
        self.files_list_frame = ctk.CTkScrollableFrame(preview_frame, height=200)
        self.files_list_frame.pack(pady=(15, 10), fill="both", expand=True, padx=20)


    def select_webps(self):
        files = filedialog.askopenfilenames(filetypes=[("WebP files", "*.webp")])
        if files:
            self.webp_files = list(files)
            self.update_files_list()
            self.set_selected_file(self.webp_files[0])
            self.show_preview(self.webp_files[0])

    def select_output_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_folder = folder
            self.save_current_settings()

    def show_preview(self, filepath):
        try:
            self.preview_running = False
            with Image.open(filepath) as im:
                frames = []
                base_frame = im.convert("RGBA")
                frames.append(ImageTk.PhotoImage(base_frame.copy().resize((400, 400))))

                try:
                    while True:
                        im.seek(im.tell() + 1)
                        frame = im.convert("RGBA")
                        composed_frame = Image.alpha_composite(base_frame, frame)
                        base_frame = composed_frame
                        frames.append(ImageTk.PhotoImage(composed_frame.copy().resize((400, 400))))
                except EOFError:
                    pass

                self.preview_frames = frames
                self.preview_index = 0

                if frames:
                    self.preview_label.configure(image=frames[0], text="")
                    self.preview_label.image = frames[0]
                    self.preview_running = True
                    self.animate_preview()
                    self.preview_label.bind("<Enter>", lambda e: self.pause_preview())
                    self.preview_label.bind("<Leave>", lambda e: self.resume_preview())
        except Exception as e:
            print(f"Error showing preview: {e}")
            self.preview_label.configure(text="No preview", image="")

    def animate_preview(self):
        if self.preview_frames and self.preview_running:
            frame = self.preview_frames[self.preview_index]
            self.preview_label.configure(image=frame, text="")
            self.preview_label.image = frame
            self.preview_index = (self.preview_index + 1) % len(self.preview_frames)
            self.after(100, self.animate_preview)

    def pause_preview(self):
        self.preview_running = False

    def resume_preview(self):
        if not self.preview_running:
            self.preview_running = True
            self.animate_preview()

    def update_files_list(self):
        for widget in self.files_list_frame.winfo_children():
            widget.destroy()
        self.file_rows = {}

        for idx, file in enumerate(self.webp_files):
            item = ctk.CTkFrame(self.files_list_frame, fg_color="#2a2a2a", corner_radius=8)
            item.pack(fill="x", padx=5, pady=3)
            self.file_rows[file] = item

            def on_enter(e, row=item):
                if self.selected_file != file:
                    row.configure(fg_color="#3a3a3a")

            def on_leave(e, row=item):
                if self.selected_file != file:
                    row.configure(fg_color="#2a2a2a")

            def on_click(e, path=file):
                self.show_preview(path)
                self.set_selected_file(path)

            file_path = Path(file)
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)

            try:
                with Image.open(file_path) as im:
                    frame_count = sum(1 for _ in ImageSequence.Iterator(im))
            except:
                frame_count = 0

            fps = self.fps_value.get()
            duration_sec = frame_count / fps if fps else 0

            info_text = f"{file_path.name}\n• {file_size_mb:.1f} MB — {frame_count} frames — {duration_sec:.1f}s @ {fps} FPS"

            label = ctk.CTkLabel(item, text=info_text, anchor="w", justify="left", font=("Arial", 12))
            label.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
            label.bind("<Button-1>", on_click)

            remove_btn = ctk.CTkButton(item, text="❌", width=30, height=30, fg_color="#444", hover_color="#aa0000", text_color="white",
                                       command=lambda i=idx: self.remove_file(i))
            remove_btn.pack(side="right", padx=(0, 10), pady=5)

            item.bind("<Enter>", on_enter)
            item.bind("<Leave>", on_leave)
            label.bind("<Enter>", on_enter)
            label.bind("<Leave>", on_leave)
            remove_btn.bind("<Enter>", on_enter)
            remove_btn.bind("<Leave>", on_leave)

    def set_selected_file(self, path):
        if self.selected_file and self.selected_file in self.file_rows:
            self.file_rows[self.selected_file].configure(fg_color="#2a2a2a")
        
        self.selected_file = path

        self.update_files_list()
        if path in self.file_rows:
            self.file_rows[path].configure(fg_color="#004488")

    def remove_file(self, index):
        if 0 <= index < len(self.webp_files):
            del self.webp_files[index]
            self.update_files_list()

    def clear_file_list(self):
        self.webp_files = []
        self.update_files_list()
        self.preview_label.configure(image="", text="No preview")

    def open_output_folder(self):
        if os.path.exists(self.output_folder):
            if sys.platform == "win32":
                os.startfile(self.output_folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", self.output_folder])
            else:
                subprocess.Popen(["xdg-open", self.output_folder])

    def start_conversion_thread(self):
        threading.Thread(target=self.start_conversion, daemon=True).start()

    def start_conversion(self):
        if not self.webp_files:
            self.show_toast("⚠️ Please select at least one WebP file.", bg="#882222")
            return

        temp_dir = Path("temp_frames")
        temp_dir.mkdir(exist_ok=True)
        fps = self.fps_value.get()
        format_choice = self.output_format.get()

        if self.combine_videos.get() and format_choice == ".gif":
            self.show_toast("⚠️ Cannot combine multiple files into a GIF.", bg="#882222")
            return

        if self.combine_videos.get():
            frame_counter = 0
            all_frames = []
            for idx, webp_file in enumerate(self.webp_files, 1):
                
                self.progress_text.configure(text=f"Extracting {idx}/{len(self.webp_files)}")
                extracted = self.extract_frames(webp_file, temp_dir, start_idx=frame_counter)
                frame_counter += len(extracted)
                self.frame_counter.configure(text=f"Frames extracted: {frame_counter}")
            all_frames = sorted(temp_dir.glob("frame_*.png"))
            all_frames = [str(p) for p in all_frames]
            if all_frames:
                output_path = os.path.join(self.output_folder, f"combined_{uuid.uuid4().hex[:6]}{format_choice}")
                self.convert_to_video(all_frames, fps, output_path, format_choice)
            for frame in all_frames:
                if os.path.exists(frame):
                    os.remove(frame)
        else:
            for idx, webp_file in enumerate(self.webp_files, 1):
                self.progress_text.configure(text=f"Processing {idx}/{len(self.webp_files)}")
                frames = self.extract_frames(webp_file, temp_dir)
                self.frame_counter.configure(text=f"Frames extracted: {len(frames)}")
                if frames:
                    output_path = os.path.join(self.output_folder, f"{Path(webp_file).stem}_{uuid.uuid4().hex[:6]}{format_choice}")
                    self.convert_to_video(frames, fps, output_path, format_choice)
                    for frame in frames:
                        if os.path.exists(frame):
                            os.remove(frame)
        try:
            temp_dir.rmdir()
        except:
            pass
        self.progress_text.configure(text="Done!")
        self.progress_bar.set(1)
        self.show_toast("✅ Conversion completed!", bg="#225522")

    def extract_frames(self, webp_file, temp_dir, start_idx=0):
        frames = []
        try:
            all_frames = []
            with Image.open(webp_file) as im:
                for frame in ImageSequence.Iterator(im):
                    all_frames.append(frame.copy())

            with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
                futures = []
                for i, frame in enumerate(all_frames):
                    frame_idx = start_idx + i
                    frame_path = temp_dir / f"frame_{frame_idx:06d}.png"
                    futures.append(executor.submit(self.save_frame, frame, frame_path))
                    frames.append(str(frame_path))
        except Exception as e:
            print(f"Error extracting frames: {e}")
        return frames

    def save_frame(self, frame, path):
        try:
            if self.resolution_preset.get() != "Same Resolution":
                target_size = RESOLUTION_MAP.get(self.resolution_preset.get())
                if target_size:
                    frame = frame.resize(target_size, Image.LANCZOS)
            frame.convert("RGBA").save(path)
        except Exception as e:
            print(f"Error saving frame: {e}")

    def convert_to_video(self, frames, fps, output_path, format_choice):
        if format_choice == ".gif":
            try:
                images = [Image.open(f).convert("RGBA") for f in frames]
                images[0].save(
                    output_path,
                    save_all=True,
                    append_images=images[1:],
                    duration=int(1000/fps),
                    loop=0,
                    optimize=True,
                    quality=95,
                    disposal=2
                )
            except Exception as e:
                print(f"Error creating GIF: {e}")
        else:
            try:
                clip = ImageSequenceClip(frames, fps=fps)
                codec = {
                    ".mp4": "libx264",
                    ".mkv": "libx264",
                    ".webm": "libvpx-vp9"
                }.get(format_choice, "libx264")

                crf = str(self.crf_value.get())

                clip.write_videofile(
                    output_path,
                    codec=codec,
                    audio=False,
                    preset="medium",
                    ffmpeg_params=["-crf", crf, "-pix_fmt", "yuv420p"],
                    logger=None
                )
                clip.close()
            except Exception as e:
                print(f"Error creating video: {e}")

    def save_current_settings(self):
        settings = {"fps": self.fps_value.get(), "format": self.output_format.get(), "output_folder": self.output_folder}
        save_settings(settings)

    def load_previous_settings(self):
        settings = load_settings()
        if settings:
            self.fps_value.set(settings.get("fps", 16))
            self.output_format.set(settings.get("format", ".mp4"))
            self.output_folder = settings.get("output_folder", os.getcwd())

    def show_toast(self, message, duration=2500, bg="#333333"):
        toast = ctk.CTkToplevel(self)
        toast.overrideredirect(True)
        toast.configure(fg_color=bg)
        toast.wm_attributes("-topmost", True)

        label = ctk.CTkLabel(toast, text=message, font=("Arial", 14), text_color="white")
        label.pack(padx=20, pady=10)

        x = self.winfo_x() + self.winfo_width() - 320
        y = self.winfo_y() + self.winfo_height() - 100
        toast.geometry(f"300x60+{x}+{y}")

        self.after(duration, toast.destroy)

if __name__ == "__main__":
    app = WebPConverterApp()
    app.mainloop()
