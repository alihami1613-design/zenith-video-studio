import unittest

from video_color import build_color_filter


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
        self.assertIn("gm=0.038", result)

    def test_rejects_out_of_range_and_non_finite_values(self):
        with self.assertRaises(ValueError):
            build_color_filter({"exposure": 5})
        with self.assertRaises(ValueError):
            build_color_filter({"contrast": float("nan")})


if __name__ == "__main__":
    unittest.main()
