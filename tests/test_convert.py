import os
import re
import subprocess
import tempfile
import unittest

import imageio_ffmpeg
from PIL import Image

import webp_converter_gui as G
from tests.support import AppFixture, make_webp, pump, source_frames, wait_until


class ConvertFixture(AppFixture):
    """An app with the class's samples queued, and a way to convert them."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.samples = cls.make_samples()
        cls.app._add_files(cls.samples)
        wait_until(cls.app, lambda: len(cls.app.file_meta) == len(cls.samples))

    def run_conversion(self, fmt, combine=False, lossless=False):
        """Convert the queue into a fresh folder; returns it once the run ends."""
        app = self.app
        out = tempfile.mkdtemp(dir=self.tmp.name)
        app.output_folder = out
        app.output_format.set(fmt)
        app.combine_videos.set(combine)
        app._on_quality_mode("Lossless" if lossless else "Compressed")
        app.start_conversion()
        self.assertTrue(app._converting, "conversion did not start")
        self.assertTrue(wait_until(app, lambda: not app._converting, timeout=180),
                        "conversion timed out")
        pump(app, 200)                  # let the final UI updates land
        return out

    def convert(self, fmt, combine=False, lossless=False):
        out = self.run_conversion(fmt, combine, lossless)
        self.assertEqual(set(self.app.file_status.values()), {"done"},
                         self.app.file_status)
        return sorted(os.listdir(out)), out


class ConvertTest(ConvertFixture, unittest.TestCase):
    """Drives real conversions through the app and checks what lands on disk."""

    @classmethod
    def make_samples(cls):
        # Different sizes, so combining has to letterbox the second clip.
        return [
            make_webp(os.path.join(cls.tmp.name, "a.webp"), size=(200, 150), frames=8),
            make_webp(os.path.join(cls.tmp.name, "b.webp"), size=(160, 160), frames=6),
        ]

    def decode(self, path):
        """Every stored frame, as ffmpeg decodes it — no resampling."""
        out = tempfile.mkdtemp(dir=self.tmp.name)
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", path,
                        "-fps_mode", "passthrough", os.path.join(out, "%05d.png")],
                       check=True, capture_output=True)
        frames = []
        for name in sorted(os.listdir(out)):
            with Image.open(os.path.join(out, name)) as im:
                frames.append(im.convert("RGBA"))
        return frames

    def assertFramesExact(self, decoded, expected, with_alpha):
        # The concat demuxer repeats the last frame so its duration is honoured.
        self.assertIn(len(decoded), (len(expected), len(expected) + 1))
        mode = "RGBA" if with_alpha else "RGB"
        for i, (got, want) in enumerate(zip(decoded, expected)):
            self.assertEqual(got.size, want.size, f"frame {i}")
            self.assertTrue(got.convert(mode).tobytes() == want.convert(mode).tobytes(),
                            f"frame {i} differs ({mode})")

    # ── Compressed ───────────────────────────

    def test_each_format_writes_one_file_per_input(self):
        for fmt in (".mp4", ".mkv", ".webm", ".gif"):
            with self.subTest(fmt=fmt):
                names, out = self.convert(fmt)
                self.assertEqual(names, [f"a{fmt}", f"b{fmt}"])
                for name in names:
                    self.assertGreater(os.path.getsize(os.path.join(out, name)), 0)

    def test_combine_writes_a_single_file(self):
        names, out = self.convert(".mp4", combine=True)
        self.assertEqual(names, ["combined.mp4"])
        self.assertGreater(os.path.getsize(os.path.join(out, names[0])), 0)

    # ── Lossless ─────────────────────────────

    def test_lossless_is_bit_exact_in_every_video_container(self):
        # MP4 and WebM carry no alpha, so their colour channels must match
        # exactly; MKV must match on all four channels.
        for fmt in (".mp4", ".webm", ".mkv"):
            with self.subTest(fmt=fmt):
                names, out = self.convert(fmt, lossless=True)
                self.assertEqual(names, [f"a{fmt}", f"b{fmt}"])
                for name, src in zip(names, self.samples):
                    self.assertFramesExact(self.decode(os.path.join(out, name)),
                                           source_frames(src),
                                           with_alpha=G.keeps_alpha(fmt, True))

    def test_combined_lossless_mkv_keeps_transparency_in_every_clip(self):
        names, out = self.convert(".mkv", combine=True, lossless=True)
        self.assertEqual(names, ["combined.mkv"])
        decoded = self.decode(os.path.join(out, "combined.mkv"))

        a, b = (source_frames(s) for s in self.samples)
        target = a[0].size
        expected = a + [G.letterbox(f, target, keep_alpha=True) for f in b]
        self.assertFramesExact(decoded, expected, with_alpha=True)

        # The letterboxed clip's bars are transparent, not black.
        first_b = decoded[len(a)]
        self.assertEqual(first_b.getpixel((0, target[1] // 2))[3], 0)

    def test_gif_ignores_lossless(self):
        names, out = self.convert(".gif", lossless=True)
        self.assertEqual(names, ["a.gif", "b.gif"])

    # ── Cancel ───────────────────────────────

    def test_cancel_leaves_no_output_and_no_file_marked_converting(self):
        app = self.app
        real_frames = app._frames

        def cancel_on_second_frame(*args, **kwargs):
            for i, frame in enumerate(real_frames(*args, **kwargs)):
                if i == 1:
                    app._request_cancel()
                yield frame

        app._frames = cancel_on_second_frame
        self.addCleanup(delattr, app, "_frames")
        for fmt, combine in ((".mp4", False), (".mp4", True), (".gif", False)):
            with self.subTest(fmt=fmt, combine=combine):
                out = self.run_conversion(fmt, combine)
                self.assertEqual(os.listdir(out), [])
                self.assertEqual(set(app.file_status.values()), {""}, app.file_status)
                self.assertIsNone(app._ffmpeg_proc)


class TimingTest(ConvertFixture, unittest.TestCase):
    """Original timing survives both routes: steady clips are piped to ffmpeg,
    clips whose frame durations vary go through per-frame files."""

    VARIED = [30, 50, 70, 90, 110, 130]     # none on ffmpeg's default 40 ms grid

    @classmethod
    def make_samples(cls):
        return [
            make_webp(os.path.join(cls.tmp.name, "steady.webp"), frames=6, duration=60),
            make_webp(os.path.join(cls.tmp.name, "varied.webp"),
                      frames=len(cls.VARIED), duration=cls.VARIED),
        ]

    def frame_gaps(self, path):
        """Milliseconds between consecutive stored frames, in display order."""
        out = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", path,
                              "-c", "copy", "-f", "framecrc", "-"],
                             check=True, capture_output=True, text=True).stdout
        num, den = map(int, re.search(r"#tb 0: (\d+)/(\d+)", out).groups())
        # Columns: stream, dts, pts, duration, size, crc.
        pts = sorted(int(line.split(",")[2]) for line in out.splitlines()
                     if line[:1].isdigit())
        return [1000 * (b - a) * num / den for a, b in zip(pts, pts[1:])]

    def test_steady_clip_keeps_its_rate_and_exact_frame_count(self):
        for fmt in (".mp4", ".mkv", ".webm"):
            with self.subTest(fmt=fmt):
                _, out = self.convert(fmt)
                gaps = self.frame_gaps(os.path.join(out, f"steady{fmt}"))
                self.assertEqual(len(gaps), 5)      # 6 frames, none repeated
                for gap in gaps:
                    self.assertAlmostEqual(gap, 60, delta=1)

    def test_varied_clip_keeps_each_frame_duration(self):
        _, out = self.convert(".mp4")
        gaps = self.frame_gaps(os.path.join(out, "varied.mp4"))
        # The last frame is stored twice so that its duration is kept too.
        self.assertEqual(len(gaps), len(self.VARIED))
        for gap, want in zip(gaps, self.VARIED):
            self.assertAlmostEqual(gap, want, delta=1)

    def test_fixed_fps_overrides_source_timing(self):
        self.app._on_timing_mode("Fixed FPS")
        self.addCleanup(self.app._on_timing_mode, "Original")
        self.app.fps_value.set(20)
        _, out = self.convert(".mp4")
        for name in ("steady.mp4", "varied.mp4"):
            gaps = self.frame_gaps(os.path.join(out, name))
            self.assertEqual(len(gaps), 5, name)
            for gap in gaps:
                self.assertAlmostEqual(gap, 50, delta=1)


if __name__ == "__main__":
    unittest.main()
