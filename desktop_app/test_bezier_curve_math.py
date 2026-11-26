"""Regression tests for Bezier graph handle hit testing."""
import unittest

from bezier_curve_math import nearest_handle_index


class BezierHandleHitTestingTests(unittest.TestCase):
    def test_selects_first_handle_when_it_is_nearest(self):
        self.assertEqual(nearest_handle_index(10, 10, 10, 10, 90, 90), 0)

    def test_selects_second_handle_when_it_is_nearest(self):
        self.assertEqual(nearest_handle_index(90, 90, 10, 10, 90, 90), 1)

    def test_tie_selects_first_handle(self):
        self.assertEqual(nearest_handle_index(50, 50, 40, 50, 60, 50), 0)


if __name__ == "__main__":
    unittest.main()
