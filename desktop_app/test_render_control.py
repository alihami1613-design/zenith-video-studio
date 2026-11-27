"""Tests for cancellable FFmpeg render process control."""
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from video_render import RenderCancelledError, _progress_seconds, _run


class RenderControlTests(unittest.TestCase):
    def test_reads_ffmpeg_progress_timestamp(self):
        with tempfile.TemporaryDirectory() as folder:
            progress = Path(folder) / "progress.txt"
            progress.write_text(
                "frame=25\nout_time=00:00:02.500000\nout_time_ms=2500000\nprogress=continue\n",
                encoding="utf-8",
            )
            self.assertAlmostEqual(_progress_seconds(progress), 2.5)

    def test_missing_or_incomplete_progress_is_safe(self):
        with tempfile.TemporaryDirectory() as folder:
            progress = Path(folder) / "missing.txt"
            self.assertIsNone(_progress_seconds(progress))
            progress.write_text("frame=10\nprogress=continue\n", encoding="utf-8")
            self.assertIsNone(_progress_seconds(progress))

    def test_cancel_terminates_child_process(self):
        cancel = threading.Event()
        timer = threading.Timer(0.25, cancel.set)
        timer.start()
        try:
            with self.assertRaisesRegex(RenderCancelledError, "لغو شد"):
                _run(
                    [sys.executable, "-c", "import time; time.sleep(10)"],
                    15, "test process", cancel_event=cancel,
                )
        finally:
            timer.cancel()

    def test_progress_callback_uses_ffmpeg_timestamp(self):
        with tempfile.TemporaryDirectory() as folder:
            progress = Path(folder) / "progress.txt"
            script = (
                "import pathlib,time,sys; p=pathlib.Path(sys.argv[1]); "
                "p.write_text('out_time=00:00:01.000000\\\\n'); "
                "time.sleep(0.35)"
            )
            values = []
            _run(
                [sys.executable, "-c", script, str(progress)],
                5, "test progress", progress_path=progress,
                expected_duration=2.0, progress_callback=values.append,
            )
            self.assertTrue(any(0.45 <= value <= 0.55 for value in values))
            self.assertEqual(values[-1], 1.0)


if __name__ == "__main__":
    unittest.main()
