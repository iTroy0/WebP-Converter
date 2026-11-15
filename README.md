# WebP-Converter
A simple, beautiful, and powerful tool to convert animated WebP images into videos (.mp4, .mkv, .webm, .gif).

<h1 align="center">WebP to Video Converter</h1>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.9%2B-blue.svg" alt="Python Version">
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License">
  <img src="https://img.shields.io/github/stars/iTroy0/WebP-Converter?style=social" alt="GitHub Stars">
</p>

---

## About

**WebP to Video Converter** is a modern, easy-to-use tool for converting animated `.webp` images into high-quality `.mp4`, `.mkv`, `.webm`, or `.gif` files.

Built in Python with a dark/light themed UI using [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter), direct FFmpeg encoding via [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg), and image handling by [Pillow](https://github.com/python-pillow/Pillow). Originally based on [Dunttus' webptomp4](https://github.com/Dunttus/webptomp4).

<p align="center">
  <img src="Screenshot.png" alt="WebP Converter, dark theme"/>
</p>
<p align="center">
  <img src="Screenshot-light.png" alt="WebP Converter, light theme"/>
</p>

---

## Features

- Convert animated WebP images to `.mp4`, `.mkv`, `.webm`, or `.gif`
- **Original frame timing** — preserves each frame's real duration (variable frame rate), or force a constant FPS (1-60)
- Resolution presets `480p` / `720p` / `1080p` / `4K` keep aspect ratio (no stretching), plus exact custom dimensions
- Compressed output with quality control (CRF 18-30), or **bit-exact lossless** — see [Lossless output](#lossless-output)
- Combine multiple WebP files into a single output — mixed sizes are letterboxed, GIF supported
- **Drag & drop** files or folders straight into the window
- Live progress with real encode percentage
- Animated preview with checkerboard transparency, real timing, a playback bar, and click/Space to pause
- **Result card** shows the output's file name, size, codec and timing before you convert
- Cancel running conversions instantly — no partial files left behind
- Queue with thumbnails, per-file status indicators and metadata (size, dimensions, duration)
- Clean output names (`name.mp4`, `name (1).mp4`, …) — no random suffixes
- Keyboard shortcuts: `Ctrl+O` add files, `Ctrl+Enter` convert, `Space` pause preview, `Delete` remove, `Escape` cancel
- Fully keyboard-operable: `Tab` moves between controls with a visible focus ring; arrow keys change choices, sliders, the size menu and the selected file
- Dark and light themes, toggled from the Output panel
- Settings, theme, and window size persist between sessions
- Standalone EXE/binary build via PyInstaller
- Cross-platform: Windows, macOS, Linux

---

## Lossless output

Set **Quality → Lossless** to keep every frame bit-for-bit identical to the source. Each container uses its own lossless encoder:

| Format | Encoder | Transparency |
|---|---|---|
| `.mkv` | FFV1 | kept |
| `.mp4` | H.264 (RGB, lossless) | dropped |
| `.webm` | VP9 (RGB, lossless) | dropped |

Lossless files are much larger than compressed ones, and many browsers, phones and built-in players can't open them — VLC and mpv can. MKV is the safest choice and the only one that keeps transparency. GIF is limited to 256 colours, so it has no lossless mode.

---

## Quick Start (Windows)

Download the portable EXE from [Releases](https://github.com/iTroy0/WebP-Converter/releases) — no install required.

---

## Run From Source

Requires Python 3.9+ with pip.

### Windows

```bash
# Option A: use the interactive menu
start.bat

# Option B: manual
pip install -r requirements.txt
python webp_converter_gui.py
```

### Linux / macOS

```bash
# Make the script executable (first time only)
chmod +x start.sh

# Option A: use the interactive menu
./start.sh

# Option B: manual
pip install -r requirements.txt
python3 webp_converter_gui.py
```

---

## Running Tests

The suite drives the real app window and real FFmpeg encodes, including bit-exact lossless round-trips, so it needs a desktop session. From the repository root:

```bash
python -m unittest
```

---

## Build Standalone Binary

### Windows

Run `start.bat` and choose option **2** (Build Standalone EXE).
The output will be at `dist/WebP Converter.exe`.

### Linux / macOS

```bash
chmod +x start.sh
./start.sh
# Choose option 2
```

The output will be at `dist/WebP Converter`.

---

## Project Structure

| File | Purpose |
|---|---|
| `webp_converter_gui.py` | Main application |
| `requirements.txt` | Python dependencies |
| `start.bat` | Interactive launcher/builder (Windows) |
| `start.sh` | Interactive launcher/builder (Linux/macOS) |
| `install_requirements.bat` | Quick dependency install (Windows) |
| `app_icon.ico` | Application icon |
| `tests/` | Test suite: UI behaviour, layout fit, encoding, lossless round-trips |
| `CHANGELOG.md` | What changed in each release |

---

## Support

If you find this project helpful, feel free to [buy me a coffee](https://buymeacoffee.com/itroy0)!

[![Buy Me a Coffee](https://img.shields.io/badge/-Buy%20Me%20a%20Coffee-%23FFDD00?logo=buymeacoffee&logoColor=black&style=for-the-badge)](https://buymeacoffee.com/itroy0)

---

## Credits

- UI: [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)
- FFmpeg: [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg)
- Image Handling: [Pillow](https://github.com/python-pillow/Pillow)
- Original Code: [Dunttus](https://github.com/Dunttus/webptomp4)

---

## License

This project is licensed under the MIT License.
Feel free to use, modify, and share!

---

<p align="center">Made with ❤️ by Troy</p>
