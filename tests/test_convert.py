import os
import subprocess
import tempfile
import unittest

import imageio_ffmpeg
from PIL import Image

import webp_converter_gui as G
from tests.support import AppFixture, make_webp, pump, source_frames, wait_until


class ConvertTest(AppFixture, unittest.TestCase):
    """Drives real conversions through the app and checks what lands on disk."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Different sizes, so combining has to letterbox the second clip.
        cls.samples = [
            make_webp(os.path.join(cls.tmp.name, "a.webp"), size=(200, 150), frames=8),
            make_webp(os.path.join(cls.tmp.name, "b.webp"), size=(160, 160), frames=6),
        ]
        cls.app._add_files(cls.samples)
        wait_until(cls.app, lambda: len(cls.app.file_meta) == 2)

    def convert(self, fmt, combine=False, lossless=False):
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
        self.assertEqual(set(app.file_status.values()), {"done"}, app.file_status)
        return sorted(os.listdir(out)), out

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


if __name__ == "__main__":
    unittest.main()
