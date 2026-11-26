import unittest

from color_scopes import (
    SCOPE_HEIGHT, SCOPE_WIDTH, build_histogram_command,
    calculate_rgb_histogram,
)


class RGBHistogramTests(unittest.TestCase):
    def test_counts_rgb_channels_independently(self):
        pixel_count = SCOPE_WIDTH * SCOPE_HEIGHT
        data = bytes((255, 128, 0)) * pixel_count
        red, green, blue = calculate_rgb_histogram(data)
        self.assertEqual(red[255], pixel_count)
        self.assertEqual(green[128], pixel_count)
        self.assertEqual(blue[0], pixel_count)
        self.assertEqual(sum(red), pixel_count)
        self.assertEqual(sum(green), pixel_count)
        self.assertEqual(sum(blue), pixel_count)

    def test_rejects_wrong_frame_size(self):
        with self.assertRaises(ValueError):
            calculate_rgb_histogram(b"short")

    def test_command_is_single_frame_low_resolution_and_single_thread(self):
        command = build_histogram_command("ffmpeg", "sample.mp4", 2.5)
        self.assertIn("1", command[command.index("-frames:v") + 1])
        self.assertIn("-threads", command)
        self.assertIn("256:144", command[command.index("-vf") + 1])
        self.assertEqual(command[-3:], ["-f", "rawvideo", "pipe:1"])

    def test_applies_current_grade_before_sampling(self):
        command = build_histogram_command("ffmpeg", "sample.mp4", 0, {"wheel_shadows_r": 0.5})
        filters = command[command.index("-vf") + 1]
        self.assertIn("colorbalance=", filters)

    def test_rejects_negative_timestamp(self):
        with self.assertRaises(ValueError):
            build_histogram_command("ffmpeg", "sample.mp4", -0.1)


if __name__ == "__main__":
    unittest.main()
