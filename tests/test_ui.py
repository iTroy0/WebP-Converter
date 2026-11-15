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

    def test_queue_rows_show_thumbnails(self):
        app = self.app
        self.assertTrue(wait_until(app, lambda: self.sample in app.file_thumbs))
        light, dark = app.file_thumbs[self.sample]

        def shown():
            return app.file_thumb_labels[self.sample].cget("image")

        label = app.file_thumb_labels[self.sample]
        self.assertIs(shown().cget("light_image"), light)
        self.assertIs(shown().cget("dark_image"), dark)
        self.assertEqual(tuple(shown().cget("size")), (G.THUMB, G.THUMB))
        # The slot is the thumbnail's size with or without its image, so the
        # row's text doesn't move when the image arrives.
        app.update_idletasks()
        scale = G.ctk.ScalingTracker.get_widget_scaling(label)
        self.assertEqual(label.winfo_reqwidth(), round(G.THUMB * scale))
        # The pixels are cached apart from the metadata, which keeps only facts.
        self.assertNotIn("thumbs", app.file_meta[self.sample])
        # Rebuilding the list reuses the cached pixels instead of re-reading,
        # in a new CTkImage: a shared one would keep every old row alive.
        before = shown()
        app.update_files_list()
        self.assertIsNot(shown(), before)
        self.assertIs(shown().cget("light_image"), light)
        app.clear_file_list()
        self.assertEqual(app.file_thumbs, {})

    def test_thumbnails_are_square_rounded_and_themed(self):
        from PIL import Image
        art = Image.new("RGBA", (120, 40), (0, 0, 0, 0))     # fully transparent
        light, dark = G.make_thumbs(art, 80, 12)
        for thumb in (light, dark):
            self.assertEqual(thumb.size, (80, 80))
            self.assertEqual(thumb.getpixel((0, 0))[3], 0)       # corner cut
            self.assertEqual(thumb.getpixel((40, 40))[3], 255)
        # Transparent art shows each theme's own checkerboard.
        for i, thumb in enumerate((light, dark)):
            seen = {thumb.getpixel(xy)[:3] for xy in ((30, 40), (50, 40))}
            self.assertEqual(seen, {_rgb(G.CHECK_A[i]), _rgb(G.CHECK_B[i])})

    def test_scrubber_tracks_playback_and_hides_without_a_clip(self):
        app = self.app
        self.assertEqual(len(app._preview_ends), 6)
        self.assertAlmostEqual(app._preview_ends[-1], 1.0)
        app._show_frame(2)
        self.assertAlmostEqual(app.preview_bar.get(), 0.5)       # 3 of 6 equal frames
        self.assertEqual(app.preview_bar.cget("progress_color"), G.DIM)
        app.clear_file_list()
        self.assertEqual(app.preview_bar.cget("progress_color"), G.BG)
        self.assertEqual(app.preview_bar.cget("fg_color"), G.BG)

    def test_result_summary_describes_what_convert_writes(self):
        app = self.app

        def summary():
            return app.summary_title.cget("text"), app.summary_detail.cget("text")

        try:
            title, detail = summary()
            self.assertEqual(title, "sample.mp4")
            for part in ("64×48", "H.264", "original timing"):
                self.assertIn(part, detail)
            self.assertNotIn("transparency", detail)

            self.set_format(".mkv")
            self.set_quality("Lossless")
            title, detail = summary()
            self.assertEqual(title, "sample.mkv")
            self.assertIn("FFV1 lossless", detail)
            self.assertIn("keeps transparency", detail)

            self.set_format(".gif")                 # GIF has no lossless mode
            self.assertIn("GIF", summary()[1])
            self.assertNotIn("lossless", summary()[1])

            app._timing_mode.set("Fixed FPS")
            app._on_timing_mode("Fixed FPS")
            self.assertIn(f"{app.fps_value.get()} fps", summary()[1])

            app.resolution_preset.set("720p")
            app.toggle_custom_res_entry("720p")
            self.assertIn("960×720", summary()[1])     # 4:3 fitted into 1280×720

            self._custom("", "")
            self.assertIn("size not set", summary()[1])
            app.custom_res_width.insert(0, "300")
            app.custom_res_height.insert(0, "200")
            app._on_size_key()
            self.assertIn("300×200", summary()[1])
        finally:
            self._leave_custom()
            app._timing_mode.set("Original")
            app._on_timing_mode("Original")
            self.set_quality("Compressed")
            self.set_format(".mp4")

        # A name that is taken gets the suffix Convert would give it.
        taken = os.path.join(app.output_folder, "sample.mp4")
        open(taken, "w").close()
        try:
            app._set_controls_enabled(True)      # as the end of a conversion does
            self.assertEqual(summary()[0], "sample (1).mp4")
        finally:
            os.remove(taken)
            app._name_cache.clear()

        app.clear_file_list()
        self.assertEqual(summary()[0], "Nothing queued")

    def test_odd_digits_in_a_size_field_are_an_error_not_a_crash(self):
        # "²".isdigit() is True but int("²") raises; the summary runs on
        # every queue change, so a crash there would break the whole list.
        app = self.app
        self._custom("²", "600")
        try:
            app._on_size_key()
            self.assertIn("size not set", app.summary_detail.cget("text"))
            app.update_files_list()
            self.assertIn(self.sample, app.file_rows)
            self.assertIsNone(app._validated_settings())
            self.assertIn("whole number", app.custom_hint.cget("text"))
        finally:
            self._leave_custom()

    def test_still_image_shows_no_playback_bar(self):
        from PIL import Image
        app = self.app
        still = os.path.join(self.tmp.name, "still.webp")
        Image.new("RGBA", (40, 30), (200, 60, 60, 255)).save(still)
        app._add_files([still])
        self.assertTrue(wait_until(app, lambda: len(app.preview_frames) == 1))
        self.assertEqual(app.preview_bar.cget("progress_color"), G.BG)

    def test_result_summary_names_a_combined_output(self):
        app = self.app
        second = make_webp(os.path.join(self.tmp.name, "second.webp"),
                           size=(32, 32), frames=2)
        app._add_files([second])
        self.assertTrue(wait_until(app, lambda: second in app.file_meta))
        try:
            app.combine_check.toggle()
            title, detail = (app.summary_title.cget("text"),
                             app.summary_detail.cget("text"))
            self.assertEqual(title, "combined.mp4")
            self.assertIn("2 clips", detail)
            self.assertIn("64×48", detail)          # the first file sets the size
        finally:
            app.combine_videos.set(False)

    @unittest.skipUnless(G._HAS_DND, "tkinterdnd2 is not installed")
    def test_window_registers_as_a_drop_target(self):
        # The tkdnd Tcl package really loaded, and the window accepts files.
        app = self.app
        self.assertTrue(app.tk.call("package", "provide", "tkdnd"))
        self.assertTrue(app.tk.call("bind", app._w, "<<Drop>>"))

    def test_empty_queue_swaps_list_for_drop_target(self):
        app = self.app
        app.update_idletasks()
        self.assertTrue(app.files_list_frame._parent_frame.winfo_ismapped())
        self.assertFalse(app.drop_zone.winfo_ismapped())
        self.assertEqual(app.clear_all_btn.cget("state"), "normal")

        app.clear_file_list()
        app.update_idletasks()
        self.assertTrue(app.drop_zone.winfo_ismapped())
        self.assertFalse(app.files_list_frame._parent_frame.winfo_ismapped())
        self.assertEqual(app.clear_all_btn.cget("state"), "disabled")

    def test_queue_scrollbar_appears_only_on_overflow(self):
        app = self.app
        bar = app.files_list_frame._scrollbar
        pump(app, 100)
        self.assertFalse(bar.winfo_ismapped(), "one file should not need a scrollbar")

        many = [make_webp(os.path.join(self.tmp.name, f"many{i:02d}.webp"),
                          size=(16, 16), frames=2) for i in range(30)]
        app._add_files(many)
        self.assertTrue(wait_until(app, bar.winfo_ismapped),
                        "30 rows overflow the list but no scrollbar appeared")

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
        # The whole column tints — including the queue's own canvas.
        self.assertEqual(app.source_column.cget("fg_color"), G.DROP_TINT)
        self.assertEqual(app.files_list_frame.cget("fg_color"), G.DROP_TINT)
        app._on_drop(SimpleNamespace(data=f"{{{loose}}} {{{folder}}}"))
        self.assertEqual(app.source_column.cget("fg_color"), G.SURFACE)
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
            # Just inside the rounded bottom-left corner: clear of the sample's
            # disc and alpha band, so bare checkerboard in the new theme.
            image = app.preview_frames[0][0].cget("light_image")
            inset = 2 * G.R_CTRL
            px = image.getpixel((inset, image.height - 1 - inset))
            self.assertEqual(px[3], 255)
            self.assertIn(px[:3], {_rgb(G.tone(G.CHECK_A)), _rgb(G.tone(G.CHECK_B))})
            # ...and the very corner is cut away by the rounding.
            self.assertEqual(image.getpixel((0, image.height - 1))[3], 0)
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

    # ── Custom size form ─────────────────────

    def _custom(self, width, height):
        app = self.app
        app.resolution_preset.set("Custom")
        app.toggle_custom_res_entry("Custom")
        for entry, value in ((app.custom_res_width, width),
                             (app.custom_res_height, height)):
            entry.delete(0, "end")
            if value:
                entry.insert(0, value)
        app.update_idletasks()      # map the row: Tk can't focus an unmapped field

    def _leave_custom(self):
        self.app.resolution_preset.set("Same Resolution")
        self.app.toggle_custom_res_entry("Same Resolution")

    def test_size_fields_keep_visible_labels(self):
        labels = []

        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, G.ctk.CTkLabel):
                    labels.append(child.cget("text"))
                walk(child)

        walk(self.app.custom_res_row)
        self.assertIn("W", labels)
        self.assertIn("H", labels)

    def test_invalid_size_is_reported_next_to_the_field(self):
        app = self.app
        self._custom("800", "9999")
        toasts = len(app._toasts)
        try:
            self.assertIsNone(app._validated_settings())
            pump(app, 50)
            self.assertEqual(len(app._toasts), toasts, "field errors must not toast")
            self.assertEqual(app.custom_res_height.cget("border_color"), G.DANGER)
            self.assertEqual(app.custom_res_width.cget("border_color"), G.RAISED)
            self.assertTrue(app.custom_hint.cget("text").startswith("✕"))
            self.assertIn("Height", app.custom_hint.cget("text"))
            self.assertEqual(app.custom_hint.cget("text_color"), G.DANGER)
            # focus_lastfor: the window's focus widget, even if another
            # application currently has the OS focus.
            self.assertIs(app.focus_lastfor(), app.custom_res_height._entry)
        finally:
            self._leave_custom()
        self.assertEqual(app.custom_hint.cget("text"), G.HINT_CUSTOM)

    def test_size_error_clears_as_you_fix_it(self):
        app = self.app
        self._custom("abc", "600")
        try:
            app._on_size_blur()
            self.assertIn("whole number", app.custom_hint.cget("text"))
            app.custom_res_width.delete(0, "end")
            app.custom_res_width.insert(0, "800")
            app._on_size_key()
            self.assertEqual(app.custom_hint.cget("text"), G.HINT_CUSTOM)
            self.assertEqual(app.custom_res_width.cget("border_color"), G.RAISED)
        finally:
            self._leave_custom()

    def test_typing_and_empty_fields_are_not_flagged_early(self):
        app = self.app
        self._custom("", "")
        try:
            app.custom_res_width.insert(0, "1")      # on the way to "128"
            app._on_size_key()
            self.assertEqual(app.custom_hint.cget("text"), G.HINT_CUSTOM)
            app.custom_res_width.delete(0, "end")
            app._on_size_blur()                        # left empty: not yet an error
            self.assertEqual(app.custom_hint.cget("text"), G.HINT_CUSTOM)
            self.assertIsNone(app._validated_settings())   # but Convert insists
            self.assertIn("Enter a width", app.custom_hint.cget("text"))
        finally:
            self._leave_custom()

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
            # Disabled: the thumb sinks into the track, so nothing looks chosen.
            self.assertEqual(app.quality_seg.cget("selected_color"), G.SEG_TRACK)
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
        controls = (app.add_files_btn, app.add_folder_btn, app.clear_all_btn,
                    app.crf_slider, app.format_seg, app.quality_seg, app.timing_seg)
        app._set_controls_enabled(False)
        try:
            for widget in controls:
                self.assertEqual(self.state(widget), "disabled")
        finally:
            app._set_controls_enabled(True)     # never leave the shared app locked
        for widget in controls:
            self.assertEqual(self.state(widget), "normal")
        # Unlocking must not revive the rate slider while timing is Original.
        self.assertEqual(self.state(app.fps_slider), "disabled")

    def test_chosen_segment_label_is_primary_text(self):
        # Contrast relies on this: DIM on the thumb would be under 4.5:1.
        app = self.app
        try:
            for fmt in G.VALID_FORMATS:
                app.output_format.set(fmt)
                for value, button in app.format_seg._buttons_dict.items():
                    self.assertEqual(button.cget("text_color"),
                                     G.TEXT if value == fmt else G.DIM, (fmt, value))
        finally:
            app.output_format.set(".mp4")

    def test_no_readable_label_uses_faint(self):
        # FAINT is for disabled states only, so enable everything first.
        app = self.app
        app._timing_mode.set("Fixed FPS")
        app._on_timing_mode("Fixed FPS")
        app.resolution_preset.set("Custom")
        app.toggle_custom_res_entry("Custom")
        try:
            offenders = []

            def walk(widget):
                for child in widget.winfo_children():
                    if isinstance(child, G.ctk.CTkLabel):
                        text = child.cget("text").strip()
                        # "×" between the custom size fields is decorative.
                        if text and text != "×" and child.cget("text_color") == G.FAINT:
                            offenders.append(text)
                    walk(child)

            walk(app)
            self.assertEqual(offenders, [])
            self.assertEqual(app.custom_res_width.cget("placeholder_text_color"), G.DIM)
        finally:
            app._timing_mode.set("Original")
            app._on_timing_mode("Original")
            app.resolution_preset.set("Same Resolution")
            app.toggle_custom_res_entry("Same Resolution")

    # ── Tooltips and disabled states ─────────

    def _shown_text(self, tip):
        """Show a tooltip as hovering would, and return its text."""
        pump(self.app, 50)          # settle: a theme switch remaps the window
        tip.show()
        self.assertIsNotNone(tip._tip, "tooltip did not appear")
        label = tip._tip.winfo_children()[0]
        text = label.cget("text")
        tip.hide()
        self.assertIsNone(tip._tip)
        return text

    def test_theme_tooltip_names_the_theme_it_switches_to(self):
        app = self.app
        other = "light" if app._theme == "dark" else "dark"
        self.assertEqual(self._shown_text(app._tips["theme"]), f"Switch to {other} theme")

    def test_preview_tooltip_follows_play_state(self):
        app = self.app
        self.assertIn("pause", self._shown_text(app._tips["preview"]))
        app._toggle_preview()
        try:
            self.assertIn("play", self._shown_text(app._tips["preview"]))
        finally:
            app._toggle_preview()

    def test_tooltip_waits_before_appearing_and_stays_in_the_window(self):
        app = self.app
        tip = app._tips["convert"]
        tip._schedule()
        self.assertIsNone(tip._tip, "appeared without the hover delay")
        self.assertTrue(wait_until(app, lambda: tip._tip is not None, timeout=2))
        try:
            app.update_idletasks()
            t = tip._tip
            self.assertGreaterEqual(t.winfo_x(), 0)
            self.assertGreaterEqual(t.winfo_y(), 0)
            self.assertLessEqual(t.winfo_x() + t.winfo_width(), app.winfo_width())
            self.assertLessEqual(t.winfo_y() + t.winfo_height(), app.winfo_height())
            self.assertIn("Ctrl+Enter", t.winfo_children()[0].cget("text"))
        finally:
            tip.hide()

    def test_nothing_to_preview_means_no_tooltip_and_no_pointer(self):
        app = self.app
        app.clear_file_list()
        app._tips["preview"].show()
        self.assertIsNone(app._tips["preview"]._tip)
        self.assertEqual(str(app.preview_well.cget("cursor")), "arrow")

    def test_row_remove_buttons_follow_the_lock(self):
        app = self.app
        button = app.file_remove_btns[self.sample]
        app._set_controls_enabled(False)
        try:
            self.assertEqual(button.cget("state"), "disabled")
        finally:
            app._set_controls_enabled(True)
        self.assertEqual(button.cget("state"), "normal")

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
        # Tallest state: Custom size entries, a two-line lossless hint, and
        # the two-line result summary that lossless MKV produces.
        app = self.app
        app.resolution_preset.set("Custom")
        app.toggle_custom_res_entry("Custom")
        self.set_quality("Lossless")
        self.set_format(".mkv")
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
