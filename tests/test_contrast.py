"""WCAG contrast between the design tokens that actually meet on screen."""
import unittest

import webp_converter_gui as G


def luminance(hex_colour):
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class ContrastTest(unittest.TestCase):
    """Each text token against the surfaces it actually appears on."""

    def assertContrast(self, fg_name, bg_names, minimum):
        fg = getattr(G, fg_name)
        for bg_name in bg_names:
            bg = getattr(G, bg_name)
            for theme, i in (("light", 0), ("dark", 1)):
                ratio = contrast(fg[i] if isinstance(fg, tuple) else fg, bg[i])
                with self.subTest(fg=fg_name, bg=bg_name, theme=theme):
                    self.assertGreaterEqual(round(ratio, 2), minimum,
                                            f"{ratio:.2f}:1")

    def test_primary_text_meets_4_5_on_every_surface(self):
        self.assertContrast("TEXT", ("SURFACE", "RAISED", "BG", "SELECTED",
                                     "SEG_TRACK", "SEG_THUMB", "SEG_HOVER",
                                     "DROP_TINT"), 4.5)

    def test_secondary_text_meets_4_5_where_it_appears(self):
        # Not SEG_THUMB: the chosen segment's label is always TEXT
        # (pinned in test_ui), so DIM only sits on the track and its hover.
        self.assertContrast("DIM", ("SURFACE", "RAISED", "BG", "SELECTED",
                                    "SEG_TRACK", "SEG_HOVER", "DROP_TINT"), 4.5)

    def test_accent_text_meets_4_5_where_it_appears(self):
        # Selected file name, slider readouts, output path, drop glyph.
        self.assertContrast("ACCENT_TX", ("SURFACE", "RAISED", "SELECTED",
                                          "DROP_TINT"), 4.5)

    def test_status_colours_meet_4_5_on_bar_and_toasts(self):
        for token in ("OK", "WARN", "DANGER"):
            self.assertContrast(token, ("SURFACE", "RAISED"), 4.5)

    def test_button_label_on_accent_meets_4_5(self):
        self.assertContrast("ON_ACCENT", ("ACCENT",), 4.5)

    def test_faint_is_still_fine_for_icon_glyphs(self):
        # Non-text contrast (WCAG 1.4.11) for the icon-only ✕ buttons,
        # on plain, hovered and selected rows.
        self.assertContrast("FAINT", ("SURFACE", "RAISED", "SELECTED"), 3.0)


if __name__ == "__main__":
    unittest.main()
