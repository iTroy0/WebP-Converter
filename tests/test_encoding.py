"""Pure encoding helpers — no window needed."""
import os
import tempfile
import unittest

from PIL import Image

import webp_converter_gui as G
from tests.support import make_webp


class FrameTimingTest(unittest.TestCase):
    """Timing read from the container, and when it allows piping frames."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def webp(self, name, durations):
        return make_webp(os.path.join(self.dir, name), size=(32, 24),
                         frames=len(durations), duration=durations)

    def rate(self, *clips, source_timing=True):
        files = [self.webp(f"{i}.webp", d) for i, d in enumerate(clips)]
        return G.stream_rate(files, {"source_timing": source_timing, "fps": 16})

    def test_durations_match_what_the_decoder_reports(self):
        path = self.webp("clip.webp", [30, 40, 50, 60, 70, 80])
        decoded = []
        with Image.open(path) as im:
            for i in range(im.n_frames):
                im.seek(i)
                im.load()
                decoded.append(im.info["duration"])
        self.assertEqual(decoded, [30, 40, 50, 60, 70, 80])
        self.assertEqual(G.webp_frame_durations(path), decoded)

    def test_still_image_has_no_durations_and_other_formats_are_refused(self):
        still = os.path.join(self.dir, "still.webp")
        Image.new("RGB", (8, 8)).save(still)
        self.assertEqual(G.webp_frame_durations(still), [])
        png = os.path.join(self.dir, "not-webp.webp")
        Image.new("RGB", (8, 8)).save(png, "PNG")
        self.assertIsNone(G.webp_frame_durations(png))
        self.assertIsNone(G.stream_rate([png], {"source_timing": True, "fps": 16}))

    def test_steady_timing_is_one_exact_rate(self):
        self.assertEqual(self.rate([40] * 5), "5000/200")
        # 30 fps rounded to whole milliseconds is still 30 fps.
        self.assertEqual(self.rate([33, 33, 34, 33, 33, 34]), "6000/200")
        self.assertEqual(self.rate([40] * 4, [40] * 3), "7000/280")

    def test_varied_timing_cannot_be_piped(self):
        self.assertIsNone(self.rate([40, 80, 120, 40]))
        self.assertIsNone(self.rate([40] * 4, [50] * 4))    # clips disagree

    def test_fixed_fps_always_pipes_at_the_chosen_rate(self):
        self.assertEqual(self.rate([40, 80, 120, 40], source_timing=False), "16")


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


class FitBoxTest(unittest.TestCase):

    def test_never_exceeds_an_odd_box(self):
        for box in ((639, 879), (101, 57), (333, 333)):
            for src in ((64, 48), (48, 64), (100, 100), (1920, 1080)):
                w, h = G.fit_box(*src, *box)
                self.assertLessEqual(w, box[0], (src, box))
                self.assertLessEqual(h, box[1], (src, box))
                self.assertEqual((w % 2, h % 2), (0, 0), (src, box))

    def test_even_boxes_give_the_same_sizes_as_make_even(self):
        # Every encode target is even; those sizes must not have shifted.
        for src in ((1000, 563), (563, 1000), (1919, 1080), (641, 359)):
            for box in G.RESOLUTION_MAP.values():
                ratio = min(box[0] / src[0], box[1] / src[1])
                old = G.make_even(max(2, round(src[0] * ratio)),
                                  max(2, round(src[1] * ratio)))
                self.assertEqual(G.fit_box(*src, *box), old, (src, box))


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
