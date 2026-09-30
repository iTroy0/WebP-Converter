"""Pure encoding helpers — no window needed."""
import unittest

from PIL import Image

import webp_converter_gui as G


class EncoderArgsTest(unittest.TestCase):

    def test_compressed_output_uses_universally_playable_yuv420p(self):
        for fmt in (".mp4", ".mkv", ".webm"):
            with self.subTest(fmt=fmt):
                args = G.encoder_args(fmt, crf=22, lossless=False)
                self.assertIn("yuv420p", args)
                self.assertEqual(args[args.index("-crf") + 1], "22")

    def test_lossless_never_uses_chroma_subsampling(self):
        # yuv420p discards colour even at qp 0 — lossless must avoid it.
        expected = {".mp4": ("libx264rgb", "rgb24"),
                    ".mkv": ("ffv1", "rgb32"),
                    ".webm": ("libvpx-vp9", "gbrp")}
        for fmt, (codec, pix_fmt) in expected.items():
            with self.subTest(fmt=fmt):
                args = G.encoder_args(fmt, crf=22, lossless=True)
                self.assertEqual(args[args.index("-c:v") + 1], codec)
                self.assertEqual(args[args.index("-pix_fmt") + 1], pix_fmt)
                self.assertNotIn("yuv420p", args)
                self.assertNotIn("-crf", args)

    def test_mp4_always_gets_faststart(self):
        for lossless in (False, True):
            self.assertIn("+faststart", G.encoder_args(".mp4", 22, lossless))

    def test_lossless_table_is_not_mutated_by_callers(self):
        G.encoder_args(".mp4", 22, lossless=True).append("-oops")
        self.assertNotIn("-oops", G.LOSSLESS_ARGS[".mp4"])

    def test_only_lossless_mkv_keeps_alpha(self):
        self.assertTrue(G.keeps_alpha(".mkv", True))
        for fmt, lossless in ((".mkv", False), (".mp4", True), (".webm", True),
                              (".gif", True)):
            self.assertFalse(G.keeps_alpha(fmt, lossless), (fmt, lossless))


class LetterboxTest(unittest.TestCase):

    def setUp(self):
        # Square, half-transparent image letterboxed into a wide frame.
        self.img = Image.new("RGBA", (40, 40), (200, 100, 50, 128))

    def test_default_bars_are_opaque_black(self):
        out = G.letterbox(self.img, (80, 40))
        self.assertEqual(out.getpixel((0, 20)), (0, 0, 0, 255))
        self.assertEqual(out.getpixel((79, 20)), (0, 0, 0, 255))

    def test_keep_alpha_bars_are_transparent_and_pixels_untouched(self):
        out = G.letterbox(self.img, (80, 40), keep_alpha=True)
        self.assertEqual(out.getpixel((0, 20))[3], 0)
        self.assertEqual(out.getpixel((79, 20))[3], 0)
        # Copied, not blended: partial alpha survives unchanged.
        self.assertEqual(out.getpixel((40, 20)), (200, 100, 50, 128))

    def test_same_size_is_returned_as_is(self):
        self.assertIs(G.letterbox(self.img, (40, 40), keep_alpha=True), self.img)


if __name__ == "__main__":
    unittest.main()
