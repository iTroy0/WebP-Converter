"""Keyboard access: Tab order, focus rings, and each control's keys."""
import os
import tkinter as tk
import unittest
from types import SimpleNamespace

import webp_converter_gui as G
from tests.support import AppFixture, make_webp, pump, wait_until


class KeyboardTest(AppFixture, unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.samples = [make_webp(os.path.join(cls.tmp.name, f"k{i}.webp"),
                                 size=(48, 36), frames=3) for i in range(3)]

    def setUp(self):
        app = self.app
        if app.webp_files != self.samples:
            app.clear_file_list()
            app._add_files(self.samples)
        wait_until(app, lambda: len(app.file_meta) == 3 and app.preview_frames)
        app.set_selected_file(self.samples[0])
        app.focus_set()
        pump(app, 50)

    def key(self, target, keysym):
        """Press a key on target the way a user would: focus it, then type.

        Tk delivers key events to the focused widget, and only while the
        window has OS focus, so the window has to take it first.
        """
        # tk.Misc directly: several CTk widgets override focus_force() to focus
        # an inner label instead; Tab traversal goes through Tk like this.
        tk.Misc.focus_force(target)
        pump(self.app, 30)
        if self.app.focus_get() is not target:
            self.skipTest("the test window could not take keyboard focus")
        target.event_generate(f"<KeyPress-{keysym}>")
        pump(self.app, 30)

    def tab_stops(self):
        """Every widget Tab visits from the window, in order."""
        stops, w = [], self.app
        for _ in range(80):
            w = w.tk_focusNext()
            if w is None or str(w) in stops:
                break
            stops.append(str(w))
        return stops

    # ── Tab order ────────────────────────────

    def test_tab_visits_every_enabled_control_in_visual_order(self):
        app = self.app
        expected = [app.clear_all_btn, app.add_files_btn, app.add_folder_btn,
                    app.files_list_frame, app.theme_btn, app.format_seg,
                    app.res_menu, app.quality_seg, app.crf_slider,
                    app.timing_seg,          # Rate is skipped: timing is Original
                    app.combine_check, app.output_folder_btn, app.convert_btn]
        self.assertEqual(self.tab_stops(), [str(w) for w in expected])

    def test_disabled_controls_leave_the_tab_order(self):
        app = self.app
        app._set_controls_enabled(False)
        try:
            stops = self.tab_stops()
            for widget in (app.add_files_btn, app.format_seg, app.crf_slider,
                           app.combine_check, app.output_folder_btn):
                self.assertNotIn(str(widget), stops)
            # Convert stays reachable: during a conversion it is Cancel.
            self.assertIn(str(app.convert_btn), stops)
        finally:
            app._set_controls_enabled(True)

    def test_custom_size_fields_join_the_tab_order_when_shown(self):
        app = self.app
        app.resolution_preset.set("Custom")
        app.toggle_custom_res_entry("Custom")
        pump(app, 50)
        try:
            stops = self.tab_stops()
            i = stops.index(str(app.res_menu))
            self.assertEqual(stops[i + 1:i + 3], [str(app.custom_res_width._entry),
                                                  str(app.custom_res_height._entry)])
        finally:
            app.resolution_preset.set("Same Resolution")
            app.toggle_custom_res_entry("Same Resolution")

    # ── Focus rings ──────────────────────────

    def ring_of(self, widget):
        return widget.master

    def test_ring_shows_only_while_focused(self):
        app = self.app
        ring = self.ring_of(app.format_seg)
        self.assertEqual(ring.cget("border_width"), 0)
        app.format_seg.event_generate("<FocusIn>")
        self.assertEqual(ring.cget("border_width"), G.RING_W)
        self.assertEqual(ring.cget("border_color"), G.FOCUS)
        app.format_seg.event_generate("<FocusOut>")
        self.assertEqual(ring.cget("border_width"), 0)

    def test_ring_is_concentric_with_the_control(self):
        ring = self.ring_of(self.app.convert_btn)
        self.assertEqual(ring.cget("corner_radius"),
                         self.app.convert_btn.cget("corner_radius") + G.RING)

    def test_clicking_clears_keyboard_focus(self):
        app = self.app
        app.format_seg.focus_set()
        app._on_click_anywhere(SimpleNamespace(widget=app.crf_slider))
        self.assertIs(app.focus_lastfor(), app)

    def test_clicking_a_text_field_keeps_its_focus(self):
        app = self.app
        app.resolution_preset.set("Custom")          # Tk won't focus a hidden field
        app.toggle_custom_res_entry("Custom")
        pump(app, 50)
        try:
            entry = app.custom_res_width._entry
            entry.focus_set()
            app._on_click_anywhere(SimpleNamespace(widget=entry))
            self.assertIs(app.focus_lastfor(), entry)
        finally:
            app.resolution_preset.set("Same Resolution")
            app.toggle_custom_res_entry("Same Resolution")

    # ── Keys ─────────────────────────────────

    def test_arrows_move_segmented_choice_and_run_its_command(self):
        app = self.app
        app.output_format.set(".mp4")
        app._sync_controls()
        try:
            self.key(app.format_seg, "Right")
            self.assertEqual(app.output_format.get(), ".mkv")
            self.key(app.quality_seg, "Right")
            self.assertTrue(app.lossless.get())
            self.assertEqual(app.quality_hint.cget("text"), G.HINT_LOSSLESS[".mkv"])
            self.key(app.format_seg, "Left")
            self.key(app.format_seg, "Left")     # stops at the first value
            self.assertEqual(app.output_format.get(), ".mp4")
        finally:
            app._quality_mode.set("Compressed")
            app._on_quality_mode("Compressed")
            app.output_format.set(".mp4")
            app._sync_controls()

    def test_arrows_step_a_slider_and_update_its_readout(self):
        app = self.app
        app.crf_value.set(22)
        app.crf_slider.set(22)
        self.key(app.crf_slider, "Right")
        self.assertEqual(app.crf_value.get(), 23)
        self.assertEqual(app.crf_label.cget("text"), "23 CRF")
        for _ in range(20):
            self.key(app.crf_slider, "Right")
        self.assertEqual(app.crf_value.get(), 30)       # clamped
        app.crf_value.set(22)
        app.crf_slider.set(22)

    def test_disabled_slider_ignores_keys(self):
        app = self.app            # Rate is disabled while timing is Original
        before = app.fps_value.get()
        self.key(app.fps_slider, "Right")
        self.assertEqual(app.fps_value.get(), before)

    def test_arrows_cycle_the_size_menu(self):
        app = self.app
        try:
            self.key(app.res_menu, "Down")
            self.assertEqual(app.resolution_preset.get(), "480p")
            for _ in range(10):
                self.key(app.res_menu, "Down")
            self.assertEqual(app.resolution_preset.get(), "Custom")
            self.assertTrue(app.custom_res_row.winfo_ismapped())
        finally:
            app.resolution_preset.set("Same Resolution")
            app.toggle_custom_res_entry("Same Resolution")

    def test_space_activates_buttons_without_toggling_the_preview(self):
        app = self.app
        theme, running = app._theme, app.preview_running
        self.key(app.theme_btn, "space")
        pump(app, 200)
        self.assertNotEqual(app._theme, theme)
        self.assertEqual(app.preview_running, running,
                         "Space reached the window-wide pause shortcut")
        self.key(app.theme_btn, "Return")
        pump(app, 200)
        self.assertEqual(app._theme, theme)

    def test_space_toggles_the_checkbox(self):
        app = self.app
        before = app.combine_videos.get()
        self.key(app.combine_check, "space")
        self.assertNotEqual(app.combine_videos.get(), before)
        self.key(app.combine_check, "space")
        self.assertEqual(app.combine_videos.get(), before)

    def test_arrows_walk_the_queue(self):
        app = self.app
        self.key(app.files_list_frame, "Down")
        self.assertEqual(app.selected_file, self.samples[1])
        self.key(app.files_list_frame, "End")
        self.assertEqual(app.selected_file, self.samples[2])
        self.key(app.files_list_frame, "Down")          # already last
        self.assertEqual(app.selected_file, self.samples[2])
        self.key(app.files_list_frame, "Home")
        self.assertEqual(app.selected_file, self.samples[0])

    def test_delete_in_a_text_field_edits_text_not_the_queue(self):
        app = self.app
        app._on_delete(SimpleNamespace(widget=app.custom_res_width._entry))
        self.assertEqual(len(app.webp_files), 3)
        app._on_delete(SimpleNamespace(widget=app))
        self.assertEqual(len(app.webp_files), 2)


if __name__ == "__main__":
    unittest.main()
