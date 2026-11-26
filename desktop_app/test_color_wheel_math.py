import unittest

from color_wheel_math import rgb_to_wheel, wheel_to_rgb


class ColorWheelMathTests(unittest.TestCase):
    def test_center_is_neutral(self):
        self.assertEqual(wheel_to_rgb(0.0, 0.0), (0.0, 0.0, 0.0))

    def test_wheel_offsets_are_balanced(self):
        for point in ((1.0, 0.0), (0.0, 1.0), (-0.6, 0.4), (0.2, -0.9)):
            rgb = wheel_to_rgb(*point)
            self.assertAlmostEqual(sum(rgb), 0.0, places=7)
            self.assertTrue(all(-1.0 <= value <= 1.0 for value in rgb))

    def test_outside_drag_is_clamped_to_unit_circle(self):
        x, y = rgb_to_wheel(*wheel_to_rgb(3.0, 4.0))
        self.assertAlmostEqual((x * x + y * y) ** 0.5, 1.0, places=7)

    def test_round_trip_preserves_wheel_position(self):
        for point in ((0.4, 0.2), (-0.5, 0.3), (0.0, -0.8)):
            restored = rgb_to_wheel(*wheel_to_rgb(*point))
            self.assertAlmostEqual(restored[0], point[0], places=7)
            self.assertAlmostEqual(restored[1], point[1], places=7)

    def test_legacy_rgb_values_are_projected_safely(self):
        x, y = rgb_to_wheel(0.8, -0.2, 0.1)
        self.assertLessEqual(x * x + y * y, 1.0 + 1e-9)


if __name__ == "__main__":
    unittest.main()
