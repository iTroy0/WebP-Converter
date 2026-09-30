"""Shared fixtures for the test suite.

The app is a real Tk window, so the tests need a desktop session. Run them from
the repository root with the interpreter that has the app's requirements:

    python -m unittest
"""
import math
import os
import tempfile
import time

from PIL import Image, ImageDraw

import webp_converter_gui as G


def make_webp(path, size=(160, 120), frames=6, duration=60, alpha=True):
    """Write a lossless animated WebP: a disc orbiting on a transparent field.

    A semi-transparent band along the top edge exercises partial alpha.
    """
    w, h = size
    images = []
    for i in range(frames):
        im = Image.new("RGBA", size, (0, 0, 0, 0) if alpha else (30, 30, 30, 255))
        draw = ImageDraw.Draw(im)
        angle = 2 * math.pi * i / frames
        cx = w / 2 + math.cos(angle) * w / 5
        cy = h / 2 + math.sin(angle) * h / 5
        r = min(w, h) / 6
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(68, 99, 250, 255))
        if alpha:
            draw.rectangle([0, 0, w, 3], fill=(240, 60, 40, 128))
        images.append(im)
    images[0].save(path, save_all=True, append_images=images[1:],
                   duration=duration, loop=0, lossless=True)
    return path


def source_frames(path):
    """The WebP's frames as RGBA images, decoded the way the app decodes them."""
    with Image.open(path) as im:
        frames = []
        for i in range(im.n_frames):
            im.seek(i)
            frames.append(im.convert("RGBA").copy())
        return frames


def pump(app, ms=50):
    """Run the real event loop for ms milliseconds.

    Worker threads hand Tk calls to the main thread, and _tkinter only accepts
    them while mainloop() is running — update() alone would leave them stalled.
    """
    app.after(ms, app.quit)
    app.mainloop()


def wait_until(app, predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        pump(app)
    return bool(predicate())


def body_panels(app):
    """The three column cards, left to right."""
    for child in app.winfo_children():
        slaves = child.grid_slaves()
        if len(slaves) == 3:
            return sorted(slaves, key=lambda s: int(s.grid_info()["column"]))
    raise AssertionError("three-column body not found")


class AppFixture:
    """One real app per test class, with settings isolated in a temp dir."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls._real_settings_file = G.SETTINGS_FILE
        G.SETTINGS_FILE = os.path.join(cls.tmp.name, "settings.json")
        cls.app = G.WebPConverterApp()
        cls.app.output_folder = cls.tmp.name
        cls.app._refresh_output_label()
        pump(cls.app, 200)

    @classmethod
    def tearDownClass(cls):
        # Each Tk root has its own interpreter but they share this thread's
        # event loop: a pending toast timer would fire into the next test
        # class's mainloop after this app is gone.
        for after_id in cls.app.tk.call("after", "info"):
            cls.app.after_cancel(after_id)
        cls.app._on_close()
        G.SETTINGS_FILE = cls._real_settings_file
        cls.tmp.cleanup()
