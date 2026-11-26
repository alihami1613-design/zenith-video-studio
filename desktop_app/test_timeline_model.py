"""Unit tests for the frame-based ZENITH timeline model.

Run from the repository root:
    python -m unittest discover -s desktop_app -p "test_*.py"
"""
import unittest

from timeline_model import TimelineProject


class TimelineModelTests(unittest.TestCase):
    def test_add_and_round_trip(self):
        project = TimelineProject(fps=30)
        clip = project.add_clip("media/a.mp4", "a.mp4", duration_frames=240)
        restored = TimelineProject.from_dict(project.to_dict())
        self.assertEqual(restored.fps, 30)
        self.assertEqual(restored.clips[0].clip_id, clip.clip_id)
        self.assertEqual(restored.duration_frames, 240)

    def test_split_preserves_source_continuity(self):
        project = TimelineProject()
        clip = project.add_clip("a.mp4", "a.mp4", start_frame=30, duration_frames=120)
        left, right = project.split_clip(clip.clip_id, 90)
        self.assertEqual((left.duration_frames, right.duration_frames), (60, 60))
        self.assertEqual(right.source_in, 60)
        self.assertEqual(right.start_frame, 90)

    def test_trim_updates_source_in(self):
        project = TimelineProject()
        clip = project.add_clip("a.mp4", "a.mp4", start_frame=10, duration_frames=100)
        project.trim_clip(clip.clip_id, new_start_frame=20, new_end_frame=80)
        self.assertEqual(clip.source_in, 10)
        self.assertEqual(clip.start_frame, 20)
        self.assertEqual(clip.duration_frames, 60)

    def test_ripple_delete_only_shifts_following_clips_on_same_track(self):
        project = TimelineProject()
        first = project.add_clip("a.mp4", "a.mp4", start_frame=0, duration_frames=30)
        following = project.add_clip("b.mp4", "b.mp4", start_frame=60, duration_frames=30)
        other_track = project.add_clip("c.wav", "c.wav", track="A1", start_frame=60, duration_frames=30)
        project.remove_clip(first.clip_id, ripple=True)
        self.assertEqual(following.start_frame, 30)
        self.assertEqual(other_track.start_frame, 60)

    def test_legacy_project_migrates_sequentially(self):
        legacy = {
            "media": [{"path": "a.mp4", "name": "a.mp4"}],
            "timeline": [
                {"path": "a.mp4", "name": "a.mp4", "track": "V1"},
                {"path": "b.mp4", "name": "b.mp4", "track": "V1"},
                {"path": "voice.wav", "name": "voice.wav", "track": "A1"},
            ],
        }
        project = TimelineProject.from_dict(legacy)
        self.assertEqual([c.start_frame for c in project.clips], [0, 150, 0])
        self.assertEqual(project.clips[2].media_type, "audio")


if __name__ == "__main__":
    unittest.main()
