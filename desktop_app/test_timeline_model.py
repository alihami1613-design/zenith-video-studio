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

    def test_audio_controls_round_trip(self):
        project = TimelineProject()
        clip = project.add_clip("voice.wav", "voice.wav", track="A1",
                                duration_frames=300, media_type="audio")
        project.set_clip_audio(clip.clip_id, volume=0.8,
                               fade_in_frames=30, fade_out_frames=45)
        restored = TimelineProject.from_dict(project.to_dict())
        saved = restored.get_clip(clip.clip_id)
        self.assertAlmostEqual(saved.volume, 0.8)
        self.assertEqual(saved.fade_in_frames, 30)
        self.assertEqual(saved.fade_out_frames, 45)
        self.assertEqual(project.to_dict()["schema_version"], 3)

    def test_legacy_clip_gets_safe_audio_defaults(self):
        project = TimelineProject.from_dict({"clips": [
            {"path": "old.wav", "name": "old.wav", "track": "A1",
             "duration_frames": 90}
        ]})
        clip = project.clips[0]
        self.assertEqual(clip.volume, 1.0)
        self.assertEqual(clip.fade_in_frames, 0)
        self.assertEqual(clip.fade_out_frames, 0)

    def test_split_keeps_fade_edges_on_outer_edges(self):
        project = TimelineProject()
        clip = project.add_clip("voice.wav", "voice.wav", track="A1",
                                duration_frames=120, media_type="audio")
        project.set_clip_audio(clip.clip_id, volume=0.7,
                               fade_in_frames=20, fade_out_frames=25)
        left, right = project.split_clip(clip.clip_id, 60)
        self.assertEqual(left.fade_in_frames, 20)
        self.assertEqual(left.fade_out_frames, 0)
        self.assertEqual(right.fade_in_frames, 0)
        self.assertEqual(right.fade_out_frames, 25)
        self.assertAlmostEqual(right.volume, 0.7)

    def test_trim_clamps_fades_and_reduces_trimmed_fade_in(self):
        project = TimelineProject()
        clip = project.add_clip("voice.wav", "voice.wav", track="A1",
                                duration_frames=120, media_type="audio")
        project.set_clip_audio(clip.clip_id, fade_in_frames=30, fade_out_frames=40)
        project.trim_clip(clip.clip_id, new_start_frame=20, new_end_frame=70)
        self.assertEqual(clip.fade_in_frames, 10)
        self.assertEqual(clip.fade_out_frames, 40)

    def test_invalid_audio_controls_are_rejected(self):
        project = TimelineProject()
        clip = project.add_clip("voice.wav", "voice.wav", track="A1",
                                duration_frames=60, media_type="audio")
        with self.assertRaises(ValueError):
            project.set_clip_audio(clip.clip_id, volume=2.1)
        with self.assertRaises(ValueError):
            project.set_clip_audio(clip.clip_id, fade_in_frames=61)

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
