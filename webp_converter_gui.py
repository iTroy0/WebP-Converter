import os
import sys
import uuid
import json
import threading
import subprocess
from pathlib import Path
from tkinter import filedialog, messagebox
import customtkinter as ctk
from PIL import Image, ImageSequence, ImageTk
from moviepy import ImageSequenceClip

# Helper to handle paths when bundled
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# Settings file
SETTINGS_FILE = "settings.json"

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
        self.geometry("750x1000")
        self.minsize(700, 950)

        self.icon_path = resource_path("app_icon.ico")
        if os.path.exists(self.icon_path):
            self.iconbitmap(self.icon_path)

        self.webp_files = []
        self.output_folder = os.getcwd()
        self.output_format = ctk.StringVar(value=".mp4")
        self.fps_value = ctk.IntVar(value=16)
        self.combine_videos = ctk.BooleanVar(value=False)

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

        ctk.CTkButton(settings_frame, text="Choose WebP File(s)", command=self.select_webps).pack(pady=8, padx=20)
        ctk.CTkButton(settings_frame, text="Select Output Folder", command=self.select_output_folder).pack(pady=8, padx=20)

        ctk.CTkLabel(settings_frame, text="Frames Per Second (FPS):", font=("Arial", 16)).pack(pady=(15, 5))
        fps_entry = ctk.CTkEntry(settings_frame, textvariable=self.fps_value)
        fps_entry.pack(pady=5, padx=50, fill="x")
        fps_entry.bind("<FocusOut>", lambda e: self.save_current_settings())

        ctk.CTkLabel(settings_frame, text="Output Format:", font=("Arial", 16)).pack(pady=(15, 5))
        format_menu = ctk.CTkOptionMenu(settings_frame, values=[".mp4", ".mkv", ".webm"], variable=self.output_format, command=lambda _: self.save_current_settings())
        format_menu.pack(pady=5)

        ctk.CTkCheckBox(settings_frame, text="Combine all videos into one", variable=self.combine_videos).pack(pady=(20, 5))

        progress_frame = ctk.CTkFrame(self.scrollable_frame)
        progress_frame.pack(fill="x", pady=20)

        ctk.CTkButton(progress_frame, text="Start Conversion", command=self.start_conversion_thread, font=("Arial", 18)).pack(pady=15)

        self.progress_bar = ctk.CTkProgressBar(progress_frame)
        self.progress_bar.pack(pady=(10, 5), fill="x", padx=40)
        self.progress_bar.set(0)

        self.progress_text = ctk.CTkLabel(progress_frame, text="0%", font=("Arial", 14))
        self.progress_text.pack(pady=5)

        self.frame_counter = ctk.CTkLabel(progress_frame, text="Frames extracted: 0", font=("Arial", 14))
        self.frame_counter.pack(pady=(5, 10))

        preview_frame = ctk.CTkFrame(self.scrollable_frame)
        preview_frame.pack(fill="both", expand=True, pady=10)

        ctk.CTkLabel(preview_frame, text="Preview Selected File:", font=("Arial", 18)).pack(pady=(5, 10))
        self.preview_label = ctk.CTkLabel(preview_frame, text="No preview")
        self.preview_label.pack(pady=(5, 10))

        self.files_list_frame = ctk.CTkScrollableFrame(preview_frame, height=200)
        self.files_list_frame.pack(pady=(5, 10), fill="both", expand=True, padx=20)

        button_frame = ctk.CTkFrame(self.scrollable_frame)
        button_frame.pack(pady=(10, 0))

        ctk.CTkButton(button_frame, text="Clear List", command=self.clear_file_list).pack(side="left", padx=10)
        ctk.CTkButton(button_frame, text="Open Output Folder", command=self.open_output_folder).pack(side="left", padx=10)

    def show_preview(self, filepath):
        try:
            self.preview_running = False  # Stop any previous animation first
            with Image.open(filepath) as im:
                frames = []
                base_frame = im.convert("RGBA")
                frames.append(ImageTk.PhotoImage(base_frame.copy().resize((300, 300))))

                try:
                    while True:
                        im.seek(im.tell() + 1)
                        frame = im.convert("RGBA")
                        composed_frame = Image.alpha_composite(base_frame, frame)
                        base_frame = composed_frame
                        frames.append(ImageTk.PhotoImage(composed_frame.copy().resize((300, 300))))
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
            self.after(100, self.animate_preview)  # Always re-call even if paused

    def pause_preview(self):
        self.preview_running = False

    def resume_preview(self):
        if not self.preview_running:
            self.preview_running = True
            self.animate_preview()

    def select_webps(self):
        files = filedialog.askopenfilenames(filetypes=[("WebP files", "*.webp")])
        if files:
            self.webp_files = list(files)
            self.show_preview(self.webp_files[0])
            self.update_files_list()

    def select_output_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_folder = folder
            self.save_current_settings()

    def update_files_list(self):
        for widget in self.files_list_frame.winfo_children():
            widget.destroy()
        for idx, file in enumerate(self.webp_files):
            item = ctk.CTkFrame(self.files_list_frame, fg_color="transparent")
            item.pack(fill="x", padx=5, pady=2)
            label = ctk.CTkLabel(item, text=Path(file).name, anchor="w", font=("Arial", 14))
            label.pack(side="left", fill="x", expand=True, padx=(5, 0))
            label.bind("<Button-1>", lambda e, path=file: self.show_preview(path))
            remove_btn = ctk.CTkButton(item, text="❌", width=30, height=30, command=lambda i=idx: self.remove_file(i))
            remove_btn.pack(side="right", padx=(0, 5))

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
            subprocess.Popen(f'explorer "{self.output_folder}"')

    def start_conversion_thread(self):
        threading.Thread(target=self.start_conversion, daemon=True).start()

    def start_conversion(self):
        if not self.webp_files:
            messagebox.showerror("Error", "Please select at least one WebP file.")
            return
        temp_dir = Path("temp_frames")
        temp_dir.mkdir(exist_ok=True)
        fps = self.fps_value.get()
        format_choice = self.output_format.get()

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
        messagebox.showinfo("Done", "Conversion completed!")

    def extract_frames(self, webp_file, temp_dir, start_idx=0):
        frames = []
        try:
            with Image.open(webp_file) as im:
                for i, frame in enumerate(ImageSequence.Iterator(im)):
                    frame_idx = start_idx + i
                    frame_path = temp_dir / f"frame_{frame_idx:06d}.png"
                    frame.convert("RGBA").save(frame_path)
                    frames.append(str(frame_path))
        except Exception as e:
            print(f"Error extracting frames: {e}")
        return frames

    def convert_to_video(self, frames, fps, output_path, format_choice):
        try:
            clip = ImageSequenceClip(frames, fps=fps)
            codec = {".mp4": "libx264", ".mkv": "libx264", ".webm": "libvpx-vp9"}.get(format_choice, "libx264")
            clip.write_videofile(output_path, codec=codec, audio=False, preset="medium", ffmpeg_params=["-crf", "23", "-pix_fmt", "yuv420p"], logger=None)
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

if __name__ == "__main__":
    app = WebPConverterApp()
    app.mainloop()
