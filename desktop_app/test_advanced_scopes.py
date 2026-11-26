import unittest

from color_scopes import SCOPE_HEIGHT, SCOPE_WIDTH
from advanced_scopes import (
    VECTOR_SIZE, calculate_luma_waveform, calculate_rgb_parade,
    calculate_vectorscope, validate_scope_matrix, validate_vectorscope_matrix,
)


class AdvancedScopeTests(unittest.TestCase):
    def test_luma_waveform_counts_every_pixel(self):
        data = bytes((255, 255, 255)) * (SCOPE_WIDTH * SCOPE_HEIGHT)
        waveform = calculate_luma_waveform(data)
        self.assertEqual(sum(map(sum, waveform)), SCOPE_WIDTH * SCOPE_HEIGHT)
        self.assertEqual(waveform[255][0], SCOPE_HEIGHT)
        self.assertEqual(waveform[0][0], 0)

    def test_rgb_parade_counts_each_channel_and_horizontal_column(self):
        data = bytes((255, 128, 0)) * (SCOPE_WIDTH * SCOPE_HEIGHT)
        red, green, blue = calculate_rgb_parade(data)
        expected = SCOPE_HEIGHT
        self.assertEqual(red[255][100], expected)
        self.assertEqual(green[128][100], expected)
        self.assertEqual(blue[0][100], expected)
        for channel in (red, green, blue):
            self.assertEqual(sum(map(sum, channel)), SCOPE_WIDTH * SCOPE_HEIGHT)

    def test_vectorscope_is_128_square_and_counts_every_pixel(self):
        data = bytes((128, 128, 128)) * (SCOPE_WIDTH * SCOPE_HEIGHT)
        scope = calculate_vectorscope(data)
        self.assertEqual(len(scope), VECTOR_SIZE)
        self.assertTrue(all(len(row) == VECTOR_SIZE for row in scope))
        self.assertEqual(sum(map(sum, scope)), SCOPE_WIDTH * SCOPE_HEIGHT)
        self.assertGreater(scope[63][63] + scope[63][64] + scope[64][63] + scope[64][64], 0)

    def test_vectorscope_separates_chromatic_primary_colors(self):
        colors = ((255, 0, 0), (0, 255, 0), (0, 0, 255))
        centers = []
        for color in colors:
            frame = bytes(color) * (SCOPE_WIDTH * SCOPE_HEIGHT)
            scope = calculate_vectorscope(frame)
            centers.append(max(
                (x, y) for y, row in enumerate(scope) for x, count in enumerate(row) if count
            ))
            self.assertEqual(sum(map(sum, scope)), SCOPE_WIDTH * SCOPE_HEIGHT)
        self.assertEqual(len(set(centers)), 3)

    def test_rejects_invalid_rgb_frame_size(self):
        with self.assertRaises(ValueError):
            calculate_rgb_parade(b"bad")
        with self.assertRaises(ValueError):
            calculate_luma_waveform(b"bad")
        with self.assertRaises(ValueError):
            calculate_vectorscope(b"bad")

    def test_validates_scope_matrix_shape_and_counts(self):
        matrix = [[0] * SCOPE_WIDTH for _ in range(256)]
        validate_scope_matrix(matrix)
        with self.assertRaises(ValueError):
            validate_scope_matrix([[0]])
        matrix[0][0] = -1
        with self.assertRaises(ValueError):
            validate_scope_matrix(matrix)

    def test_validates_vectorscope_matrix(self):
        matrix = [[0] * VECTOR_SIZE for _ in range(VECTOR_SIZE)]
        validate_vectorscope_matrix(matrix)
        with self.assertRaises(ValueError):
            validate_vectorscope_matrix([[0]])
        matrix[0][0] = -1
        with self.assertRaises(ValueError):
            validate_vectorscope_matrix(matrix)


if __name__ == "__main__":
    unittest.main()
