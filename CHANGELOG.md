# Changelog

## Unreleased

### Changed

- **Video conversion is up to 4× faster and writes no temporary files** when
  a clip plays at a steady rate, or Timing is set to Fixed FPS. Frames go
  straight to FFmpeg instead of being saved as PNGs and read back, so a big
  batch no longer fills the system drive, and the last frame is no longer
  stored twice. Only video whose frames have different durations still goes
  through temporary frames.
- GIF output is built in memory, without temporary frames, and is about a
  third quicker.
- Adding a file no longer decodes every frame to read its duration.
- Needs imageio-ffmpeg 0.6 or newer (FFmpeg 7); `requirements.txt` asks for it.

### Fixed

- Original timing was snapped to 40 ms steps: a clip faster than 25 fps lost
  frames, and other rates played unevenly or at the wrong speed.
- On a scaled Windows display (150%, for example) the window opened smaller
  than intended and could be shrunk below its contents.
- The queue's scrollbar could appear with a single file in the list.
- After Cancel, the file being converted stayed marked as converting.
- The preview tooltip stayed on screen after the queue was cleared.
- The preview caption counted at most 200 frames for a longer clip.
- The app failed to install on Python 3.15, where Pillow 11 has no build.

## 2.3.0

Everything since v2.2.

### New

- **Lossless output.** Set Quality to Lossless for bit-exact video: FFV1 in
  `.mkv` (keeps transparency), RGB H.264 in `.mp4`, RGB VP9 in `.webm`.
  Each is verified by decoding the output back and comparing every pixel.
- **Light theme**, alongside dark. Toggle it from the Output column; the
  choice is remembered.
- **Thumbnails** in the queue, so files are recognisable at a glance.
- **Result card**: the file name Convert will write, with its size, codec,
  timing and whether transparency is kept — before you convert.
- **Playback bar** under the preview.
- **Full keyboard use.** `Tab` reaches every control with a visible focus
  ring; arrow keys change choices, sliders, the size menu and the selected
  file.
- **Tooltips** with the keyboard shortcut for each action.

### Changed

- New three-column layout — Source, Preview, Output — with one slim bar at
  the bottom. It fits a 1366×768 screen; the smallest window is 1040×600.
- The preview fills the space it has and re-fits when the window is resized.
- Custom size has labelled W and H fields and reports mistakes beside the
  field instead of in a pop-up.
- All text meets WCAG AA contrast (4.5:1) in both themes.
- Disabled controls look disabled. Choosing GIF turns Quality off, since
  GIF's 256 colours make it meaningless.
- Queue rows show size, dimensions and duration; the frame count moved to
  the preview caption.

### Fixed

- Preview could come out one pixel wider than an odd-sized preview area.
- Pressing `Delete` while typing in a size field also removed the selected
  file from the queue.
- `Space` and `Delete` could act on the app while another program had focus.
- Every encode leaked two file handles.
- A long file name could push a row's remove button out of view.
- A character such as `²` in a custom size field was accepted as a number
  and then failed.
- The app failed to start on Python 3.9, which the README lists as supported.
- A window size saved on a larger monitor could open off-screen.

### For contributors

- A test suite (`python -m unittest`) covering the UI, layout, contrast,
  keyboard access, encoder arguments and lossless round-trips.

## 2.2

- Fixed frame timing, aspect ratio and race bugs; UI overhaul.

## 2.1

- Bug fixes and UX overhaul; MoviePy replaced with direct FFmpeg encoding.
