import unittest
import subprocess

from video_color import build_color_filter
from proxy_manager import find_ffmpeg


class VideoColorTests(unittest.TestCase):
    def test_default_grade_produces_no_filters(self):
        self.assertEqual(build_color_filter({}), "")

    def test_builds_exposure_contrast_and_saturation_filters(self):
        result = build_color_filter({
            "exposure": 1.25, "contrast": 1.2, "saturation": 1.35,
        })
        self.assertIn("exposure=exposure=1.250", result)
        self.assertIn("eq=contrast=1.200:saturation=1.350", result)

    def test_builds_white_balance_and_tint_filter(self):
        result = build_color_filter({"temperature": 0.5, "tint": -0.25})
        self.assertIn("colorbalance=", result)
        self.assertIn("rs=0.075", result)
        self.assertIn("bs=-0.075", result)
        self.assertIn("gm=0.037", result)

    def test_rejects_out_of_range_and_non_finite_values(self):
        with self.assertRaises(ValueError):
            build_color_filter({"exposure": 5})
        with self.assertRaises(ValueError):
            build_color_filter({"contrast": float("nan")})

    def test_builds_tonal_curve_for_highlights_shadows_whites_blacks(self):
        result = build_color_filter({
            "highlights": 0.5, "shadows": -0.3, "whites": 0.2, "blacks": -0.4,
        })
        self.assertIn("curves=master=", result)
        self.assertIn("0.000/", result)
        self.assertIn("1.000/", result)

    def test_tonal_curve_rejects_out_of_range_values(self):
        with self.assertRaises(ValueError):
            build_color_filter({"highlights": 1.1})

    def test_tonal_curve_filter_is_accepted_by_ffmpeg(self):
        ffmpeg = find_ffmpeg()
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=10:duration=0.3",
            "-vf", build_color_filter({
                "highlights": 0.4, "shadows": -0.3, "whites": 0.2, "blacks": -0.2,
            }),
            "-frames:v", "3", "-f", "null", "-",
        ]
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)


if __name__ == "__main__":
    unittest.main()
