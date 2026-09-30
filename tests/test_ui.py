import json
import os
import shutil
import unittest
from types import SimpleNamespace

import webp_converter_gui as G
from tests.support import AppFixture, body_panels, make_webp, pump, wait_until


def _rgb(hex_colour):
    return tuple(int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))


class UITest(AppFixture, unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sample = make_webp(os.path.join(cls.tmp.name, "sample.webp"),
                               size=(64, 48), frames=6, duration=80)

    def setUp(self):
        app = self.app
        if app.webp_files != [self.sample]:
            app.clear_file_list()
            app._add_files([self.sample])
        loaded = wait_until(app, lambda: app.file_meta.get(self.sample)
                            and len(app.preview_frames) == 6)
        self.assertTrue(loaded, "sample never finished loading")

    # ── Queue and preview ────────────────────

    def test_metadata_is_read(self):
        meta = self.app.file_meta[self.sample]
        self.assertEqual((meta["w"], meta["h"], meta["frames"], meta["total_ms"]),
                         (64, 48, 6, 480))

    def test_convert_button_counts_queue(self):
        self.assertIn("1 file", self.app.convert_btn.cget("text"))

    def test_preview_pause_and_play(self):
        app = self.app
        app._toggle_preview()
        self.assertFalse(app.preview_running)
        app._toggle_preview()
        self.assertTrue(app.preview_running)

    def test_clear_empties_queue_and_preview(self):
        self.app.clear_file_list()
        self.assertEqual(self.app.webp_files, [])
        self.assertEqual(self.app.preview_frames, [])
        self.assertIn("Convert", self.app.convert_btn.cget("text"))

    def test_drop_handler_adds_files_and_folders(self):
        app = self.app
        folder = os.path.join(self.tmp.name, "dropped")
        os.makedirs(folder, exist_ok=True)
        inside = make_webp(os.path.join(folder, "inside.webp"))
        loose = shutil.copy(self.sample, os.path.join(self.tmp.name, "loose.webp"))
        with open(os.path.join(folder, "notes.txt"), "w") as f:
            f.write("ignored")
        app.clear_file_list()

        app._set_drop_active(True)
        self.assertEqual(app.drop_zone.cget("fg_color"), G.DROP_TINT)
        app._on_drop(SimpleNamespace(data=f"{{{loose}}} {{{folder}}}"))
        self.assertEqual(app.drop_zone.cget("fg_color"), G.RAISED)
        self.assertEqual(sorted(map(os.path.basename, app.webp_files)),
                         ["inside.webp", "loose.webp"])
        self.assertIn(inside, app.webp_files)

    # ── Theme ────────────────────────────────

    def test_theme_toggle_rebuilds_preview_in_place(self):
        app = self.app
        start = app._theme
        for _ in range(2):
            before = app.preview_frames
            app._toggle_theme()
            # Old frames stay on screen until the rebuilt ones arrive.
            self.assertIs(app.preview_frames, before)
            self.assertTrue(wait_until(app, lambda: app.preview_frames is not before))
            # Bottom-left is clear of the sample's disc and alpha band, so it
            # shows bare checkerboard — which must be in the new theme's colours.
            image = app.preview_frames[0][0].cget("light_image")
            corner = image.getpixel((0, image.height - 1))[:3]
            self.assertIn(corner, {_rgb(G.tone(G.CHECK_A)), _rgb(G.tone(G.CHECK_B))})
        self.assertEqual(app._theme, start)

    # ── Settings form ────────────────────────

    def test_every_format_validates(self):
        app = self.app
        for fmt in G.VALID_FORMATS:
            app.output_format.set(fmt)
            self.assertEqual(app._validated_settings()["format"], fmt)
        app.output_format.set(".mp4")

    def test_custom_size_is_validated(self):
        app = self.app
        for preset in G.VALID_RESOLUTIONS:
            app.resolution_preset.set(preset)
            app.toggle_custom_res_entry(preset)
        for entry, value in ((app.custom_res_width, "800"),
                             (app.custom_res_height, "600")):
            entry.delete(0, "end")
            entry.insert(0, value)
        got = app._validated_settings()
        self.assertEqual((got["resolution"], got["custom_w"], got["custom_h"]),
                         ("Custom", 800, 600))

        app.custom_res_width.delete(0, "end")
        app.custom_res_width.insert(0, str(G.MAX_DIMENSION + 1))
        self.assertIsNone(app._validated_settings())

        app.resolution_preset.set("Same Resolution")
        app.toggle_custom_res_entry("Same Resolution")

    def test_timing_mode_drives_rate_slider(self):
        app = self.app
        for mode, rate_live in (("Fixed FPS", True), ("Original", False)):
            app._timing_mode.set(mode)
            app._on_timing_mode(mode)
            self.assertEqual(app.use_source_timing.get(), mode == "Original")
            self.assertEqual(str(app.fps_slider.cget("state")),
                             "normal" if rate_live else "disabled")

    def set_quality(self, mode):
        self.app._quality_mode.set(mode)
        self.app._on_quality_mode(mode)

    def set_format(self, fmt):
        self.app.output_format.set(fmt)
        self.app._sync_controls()       # what the segmented button's command does

    def state(self, widget):
        # CTkSegmentedButton accepts configure(state=...) but not cget("state").
        if isinstance(widget, G.ctk.CTkSegmentedButton):
            return widget._state
        return str(widget.cget("state"))

    def test_lossless_disables_crf_and_explains_the_cost(self):
        app = self.app
        try:
            for fmt in (".mp4", ".mkv", ".webm"):
                with self.subTest(fmt=fmt):
                    self.set_format(fmt)
                    self.set_quality("Lossless")
                    self.assertEqual(self.state(app.crf_slider), "disabled")
                    self.assertEqual(app.quality_hint.cget("text"), G.HINT_LOSSLESS[fmt])
                    got = app._validated_settings()
                    self.assertTrue(got["lossless"])
                    self.assertEqual(got["keep_alpha"], fmt == ".mkv")
            self.set_quality("Compressed")
            self.assertEqual(self.state(app.crf_slider), "normal")
            self.assertEqual(app.quality_hint.cget("text"), G.HINT_COMPRESSED)
        finally:
            self.set_quality("Compressed")
            self.set_format(".mp4")

    def test_gif_disables_quality_entirely(self):
        app = self.app
        try:
            self.set_quality("Lossless")
            self.set_format(".gif")
            self.assertEqual(self.state(app.quality_seg), "disabled")
            self.assertEqual(self.state(app.crf_slider), "disabled")
            self.assertEqual(app.quality_hint.cget("text"), G.HINT_GIF)
            self.assertFalse(app._validated_settings()["lossless"])
            # The muted selection must not keep the live accent colour.
            self.assertEqual(app.quality_seg.cget("selected_color"), G.HOVER)
            self.set_format(".mkv")
            self.assertEqual(self.state(app.quality_seg), "normal")
            self.assertEqual(app.quality_hint.cget("text"), G.HINT_LOSSLESS[".mkv"])
        finally:
            self.set_quality("Compressed")
            self.set_format(".mp4")

    def test_quality_hint_never_moves_the_rows_below(self):
        app = self.app
        app.update_idletasks()
        y_compressed = app.timing_seg.winfo_y()
        try:
            for fmt in (".mp4", ".mkv", ".webm", ".gif"):
                self.set_format(fmt)
                self.set_quality("Lossless")
                app.update_idletasks()
                self.assertEqual(app.timing_seg.winfo_y(), y_compressed, fmt)
        finally:
            self.set_quality("Compressed")
            self.set_format(".mp4")

    def test_lock_disables_then_restores_dependent_state(self):
        app = self.app
        app._timing_mode.set("Original")
        app._on_timing_mode("Original")
        app._set_controls_enabled(False)
        try:
            for widget in (app.add_folder_btn, app.crf_slider, app.format_seg,
                           app.quality_seg, app.timing_seg):
                self.assertEqual(self.state(widget), "disabled")
        finally:
            app._set_controls_enabled(True)     # never leave the shared app locked
        for widget in (app.add_folder_btn, app.crf_slider, app.format_seg,
                       app.quality_seg, app.timing_seg):
            self.assertEqual(self.state(widget), "normal")
        # Unlocking must not revive the rate slider while timing is Original.
        self.assertEqual(self.state(app.fps_slider), "disabled")

    def test_toasts_are_capped(self):
        app = self.app
        for kind in ("info", "ok", "warn", "err", "info"):
            app.show_toast(kind, kind=kind)
        pump(app)
        self.assertEqual(len(app._toasts), 4)
        for toast in list(app._toasts):
            app._dismiss_toast(toast)

    def test_settings_are_persisted(self):
        app = self.app
        app.save_current_settings()
        with open(G.SETTINGS_FILE) as f:
            data = json.load(f)
        self.assertEqual(data["theme"], app._theme)
        self.assertEqual(data["format"], app.output_format.get())
        self.assertEqual(data["source_timing"], app.use_source_timing.get())
        self.assertEqual(data["lossless"], app.lossless.get())

    # ── Layout ───────────────────────────────

    def assertEverythingFits(self):
        app = self.app
        app.update_idletasks()
        for name, card in zip(("source", "preview", "output"), body_panels(app)):
            self.assertLessEqual(card.winfo_reqwidth(), card.winfo_width(), name)
            self.assertLessEqual(card.winfo_reqheight(), card.winfo_height(), name)
        self.assertLessEqual(app.winfo_reqheight(), app.winfo_height())
        self.assertLessEqual(app.winfo_reqwidth(), app.winfo_width())

    def test_minimum_window_fits_tallest_settings_state(self):
        # Tallest state: Custom size entries plus the longest lossless hint.
        app = self.app
        app.resolution_preset.set("Custom")
        app.toggle_custom_res_entry("Custom")
        self.set_quality("Lossless")
        self.set_format(max(G.HINT_LOSSLESS, key=lambda f: len(G.HINT_LOSSLESS[f])))
        app.geometry(f"{G.WIN_MIN[0]}x{G.WIN_MIN[1]}")
        pump(app, 300)
        try:
            self.assertEqual((app.winfo_width(), app.winfo_height()), G.WIN_MIN)
            self.assertEverythingFits()
        finally:
            app.resolution_preset.set("Same Resolution")
            app.toggle_custom_res_entry("Same Resolution")
            self.set_quality("Compressed")
            self.set_format(".mp4")
            app.geometry(f"{G.WIN_DEFAULT[0]}x{G.WIN_DEFAULT[1]}")
            pump(app, 300)

    def _frame_size(self):
        return tuple(self.app.preview_frames[0][0].cget("size"))

    def test_preview_refits_when_window_resizes(self):
        app = self.app
        before = self._frame_size()
        app.geometry(f"{G.WIN_DEFAULT[0] + 360}x{G.WIN_DEFAULT[1] + 240}")
        try:
            self.assertTrue(wait_until(app, lambda: self._frame_size() != before),
                            "preview did not re-fit to the larger well")
            box = app._preview_box()
            w, h = self._frame_size()
            self.assertTrue(w <= box[0] and h <= box[1], f"{(w, h)} outside {box}")
        finally:
            app.geometry(f"{G.WIN_DEFAULT[0]}x{G.WIN_DEFAULT[1]}")
            wait_until(app, lambda: self._frame_size() == before)

    def test_paused_preview_keeps_its_frame_across_resize(self):
        app = self.app
        pump(app, 200)                  # let the animation move off frame 0
        app._toggle_preview()
        paused_on = app.preview_index
        before = self._frame_size()
        app.geometry(f"{G.WIN_DEFAULT[0] + 200}x{G.WIN_DEFAULT[1] + 120}")
        try:
            self.assertTrue(wait_until(app, lambda: self._frame_size() != before))
            self.assertFalse(app.preview_running)
            self.assertEqual(app.preview_index, paused_on)
        finally:
            app.geometry(f"{G.WIN_DEFAULT[0]}x{G.WIN_DEFAULT[1]}")
            wait_until(app, lambda: self._frame_size() == before)
            app._toggle_preview()


if __name__ == "__main__":
    unittest.main()
