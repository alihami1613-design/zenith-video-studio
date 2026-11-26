"""Unit tests for the frame-based ZENITH timeline model.

Run from the repository root:
    python -m unittest discover -s desktop_app -p "test_*.py"
"""
import unittest

from timeline_model import TimelineProject


class TimelineModelTests(unittest.TestCase):
    def test_video_clip_embedded_audio_is_persisted_and_migrated(self):
        project = TimelineProject()
        clip = project.add_clip(
            "camera.mp4", "camera.mp4", track="V1", duration_frames=90,
            media_type="video", has_audio=True, audio_track="A3",
        )
        restored = TimelineProject.from_dict(project.to_dict())
        saved = restored.get_clip(clip.clip_id)
        self.assertTrue(saved.has_audio)
        self.assertEqual(saved.audio_track, "A3")
        legacy = TimelineProject.from_dict({
            "fps": 30, "clips": [{
                "path": "old.mp4", "name": "old.mp4", "track": "V1",
                "media_type": "video", "duration_frames": 60,
            }]
        })
        self.assertFalse(legacy.clips[0].has_audio)
        self.assertEqual(legacy.clips[0].audio_track, "A1")


    def test_transform_keyframes_round_trip_split_and_validate(self):
        project = TimelineProject()
        clip = project.add_clip("motion.mp4", "motion.mp4", duration_frames=120)
        project.set_clip_transform_keyframes(clip.clip_id, [
            {"frame": 0, "x": -0.5, "y": 0.0, "scale": 1.0, "rotation": 0.0},
            {"frame": 90, "x": 0.5, "y": 0.25, "scale": 1.8, "rotation": 25.0},
        ])
        restored = TimelineProject.from_dict(project.to_dict())
        saved = restored.get_clip(clip.clip_id)
        self.assertEqual(len(saved.transform_keyframes), 2)
        self.assertEqual(restored.to_dict()["schema_version"], 18)
        left, right = restored.split_clip(clip.clip_id, 60)
        self.assertEqual(left.transform_keyframes[0]["frame"], 0)
        self.assertEqual(right.transform_keyframes[0]["frame"], 30)
        self.assertIsNot(left.transform_keyframes, right.transform_keyframes)

    def test_transform_bezier_handles_round_trip_and_validate(self):
        project = TimelineProject()
        clip = project.add_clip("bezier.mp4", "bezier.mp4", duration_frames=90)
        project.set_clip_transform_keyframes(clip.clip_id, [
            {"frame": 0, "scale": 1.0, "ease": "bezier",
             "bezier_y1": 0.2, "bezier_y2": 0.8},
            {"frame": 60, "scale": 2.0},
        ])
        restored = TimelineProject.from_dict(project.to_dict())
        first = restored.get_clip(clip.clip_id).transform_keyframes[0]
        self.assertEqual(first["ease"], "bezier")
        self.assertAlmostEqual(first["bezier_y1"], 0.2)
        self.assertAlmostEqual(first["bezier_y2"], 0.8)
        with self.assertRaisesRegex(ValueError, "Bezier handles"):
            project.set_clip_transform_keyframes(clip.clip_id, [
                {"frame": 0, "ease": "bezier", "bezier_y1": 1.5},
            ])

    def test_trim_preserves_transform_value_at_new_start(self):
        project = TimelineProject()
        clip = project.add_clip("motion.mp4", "motion.mp4", duration_frames=120)
        project.set_clip_transform_keyframes(clip.clip_id, [
            {"frame": 0, "x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0},
            {"frame": 60, "x": 1.0, "y": 0.5, "scale": 2.0, "rotation": 30.0},
        ])
        project.trim_clip(clip.clip_id, new_start_frame=30, new_end_frame=100)
        first = clip.transform_keyframes[0]
        self.assertEqual(first["frame"], 0)
        self.assertAlmostEqual(first["x"], 0.5)
        self.assertAlmostEqual(first["y"], 0.25)
        self.assertAlmostEqual(first["scale"], 1.5)
        self.assertAlmostEqual(first["rotation"], 15.0)

    def test_trim_after_last_transform_key_keeps_last_transform(self):
        project = TimelineProject()
        clip = project.add_clip("motion.mp4", "motion.mp4", duration_frames=120)
        project.set_clip_transform_keyframes(clip.clip_id, [
            {"frame": 10, "x": 0.4, "y": -0.2, "scale": 1.4, "rotation": 8.0},
        ])
        project.trim_clip(clip.clip_id, new_start_frame=40, new_end_frame=100)
        self.assertEqual(len(clip.transform_keyframes), 1)
        self.assertEqual(clip.transform_keyframes[0]["frame"], 0)
        self.assertAlmostEqual(clip.transform_keyframes[0]["x"], 0.4)

    def test_transform_keyframes_reject_invalid_order_and_bounds(self):
        project = TimelineProject()
        clip = project.add_clip("motion.mp4", "motion.mp4", duration_frames=60)
        with self.assertRaisesRegex(ValueError, "ordered inside"):
            project.set_clip_transform_keyframes(clip.clip_id, [
                {"frame": 20}, {"frame": 10},
            ])
        with self.assertRaisesRegex(ValueError, "scale"):
            project.set_clip_transform_keyframes(clip.clip_id, [
                {"frame": 0, "scale": 5.0},
            ])

    def test_color_grade_round_trip_and_split(self):
        project = TimelineProject()
        clip = project.add_clip("shot.mp4", "shot.mp4", duration_frames=120)
        project.set_clip_color(
            clip.clip_id, exposure=1.25, contrast=1.2, saturation=1.4,
            temperature=0.3, tint=-0.2, highlights=0.4, shadows=-0.3,
            whites=0.2, blacks=-0.1, wheel_shadows_r=0.25,
            wheel_midtones_g=-0.2, wheel_highlights_b=0.35,
        )
        restored = TimelineProject.from_dict(project.to_dict())
        saved = restored.get_clip(clip.clip_id)
        self.assertAlmostEqual(saved.color_grade["exposure"], 1.25)
        self.assertAlmostEqual(saved.color_grade["temperature"], 0.3)
        self.assertAlmostEqual(saved.color_grade["highlights"], 0.4)
        self.assertAlmostEqual(saved.color_grade["shadows"], -0.3)
        self.assertAlmostEqual(saved.color_grade["whites"], 0.2)
        self.assertAlmostEqual(saved.color_grade["blacks"], -0.1)
        self.assertAlmostEqual(saved.color_grade["wheel_shadows_r"], 0.25)
        self.assertAlmostEqual(saved.color_grade["wheel_midtones_g"], -0.2)
        self.assertAlmostEqual(saved.color_grade["wheel_highlights_b"], 0.35)
        left, right = restored.split_clip(clip.clip_id, 60)
        self.assertEqual(left.color_grade, right.color_grade)
        self.assertIsNot(left.color_grade, right.color_grade)

    def test_color_grade_rejects_invalid_values(self):
        project = TimelineProject()
        clip = project.add_clip("shot.mp4", "shot.mp4")
        with self.assertRaises(ValueError):
            project.set_clip_color(clip.clip_id, exposure=5.0)
        with self.assertRaises(ValueError):
            project.set_clip_color(clip.clip_id, saturation=float("nan"))


    def test_legacy_color_grade_gets_new_tonal_defaults(self):
        legacy = TimelineProject.from_dict({
            "schema_version": 17,
            "clips": [{
                "path": "legacy.mp4", "name": "legacy.mp4",
                "track": "V1", "duration_frames": 30,
                "color_grade": {"exposure": 0.5, "contrast": 1.1},
            }],
        })
        grade = legacy.clips[0].color_grade
        self.assertEqual(grade["highlights"], 0.0)
        self.assertEqual(grade["shadows"], 0.0)
        self.assertEqual(grade["whites"], 0.0)
        self.assertEqual(grade["blacks"], 0.0)
        self.assertEqual(grade["wheel_shadows_r"], 0.0)
        self.assertEqual(grade["wheel_midtones_g"], 0.0)
        self.assertEqual(grade["wheel_highlights_b"], 0.0)

    def test_visual_fades_round_trip_split_and_validation(self):
        project = TimelineProject()
        clip = project.add_clip("shot.mp4", "shot.mp4", duration_frames=120)
        project.set_clip_video_fade(clip.clip_id, fade_in_frames=20, fade_out_frames=30)
        restored = TimelineProject.from_dict(project.to_dict())
        saved = restored.get_clip(clip.clip_id)
        self.assertEqual(saved.video_fade_in_frames, 20)
        self.assertEqual(saved.video_fade_out_frames, 30)
        left, right = restored.split_clip(clip.clip_id, 60)
        self.assertEqual(left.video_fade_in_frames, 20)
        self.assertEqual(left.video_fade_out_frames, 0)
        self.assertEqual(right.video_fade_in_frames, 0)
        self.assertEqual(right.video_fade_out_frames, 30)
        with self.assertRaises(ValueError):
            restored.set_clip_video_fade(left.clip_id, fade_in_frames=61)

    def test_legacy_clip_gets_visual_fade_defaults(self):
        project = TimelineProject.from_dict({"clips": [
            {"path": "old.mp4", "name": "old.mp4", "track": "V1", "duration_frames": 60}
        ]})
        self.assertEqual(project.clips[0].video_fade_in_frames, 0)
        self.assertEqual(project.clips[0].video_fade_out_frames, 0)
        self.assertEqual(project.to_dict()["schema_version"], 18)

    def test_cross_dissolve_persists_and_split_does_not_duplicate_it(self):
        project = TimelineProject()
        first = project.add_clip("a.mp4", "a", start_frame=0, duration_frames=90)
        second = project.add_clip("b.mp4", "b", start_frame=90, duration_frames=90)
        second.source_in = 24
        project.set_clip_transition(second.clip_id, dissolve_in_frames=24, transition_type="wipe_left")
        restored = TimelineProject.from_dict(project.to_dict())
        incoming = restored.get_clip(second.clip_id)
        self.assertEqual(incoming.transition_in_frames, 24)
        self.assertEqual(incoming.transition_in_type, "wipe_left")
        left, right = restored.split_clip(second.clip_id, 135)
        self.assertEqual(left.transition_in_frames, 24)
        self.assertEqual(right.transition_in_frames, 0)

    def test_cross_dissolve_is_clamped_when_clip_is_trimmed_shorter(self):
        project = TimelineProject()
        project.add_clip("a.mp4", "a", start_frame=0, duration_frames=90)
        second = project.add_clip("b.mp4", "b", start_frame=90, duration_frames=90)
        second.source_in = 30
        project.set_clip_transition(second.clip_id, dissolve_in_frames=20)
        project.trim_clip(second.clip_id, new_end_frame=100)
        self.assertEqual(second.duration_frames, 10)
        self.assertEqual(second.transition_in_frames, 10)

    def test_cross_dissolve_requires_source_handles(self):
        project = TimelineProject()
        project.add_clip("a.mp4", "a", start_frame=0, duration_frames=90)
        second = project.add_clip("b.mp4", "b", start_frame=90, duration_frames=90)
        with self.assertRaisesRegex(ValueError, "source handle"):
            project.set_clip_transition(second.clip_id, dissolve_in_frames=15)

    def test_supported_transition_types_are_validated(self):
        project = TimelineProject()
        project.add_clip("a.mp4", "a", start_frame=0, duration_frames=90)
        second = project.add_clip("b.mp4", "b", start_frame=90, duration_frames=90)
        second.source_in = 30
        project.set_clip_transition(second.clip_id, dissolve_in_frames=15, transition_type="push_left")
        self.assertEqual(second.transition_in_type, "push_left")
        with self.assertRaisesRegex(ValueError, "Unsupported video transition"):
            project.set_clip_transition(second.clip_id, dissolve_in_frames=15, transition_type="spin")

    def test_cross_dissolve_duration_cannot_exceed_clip(self):
        project = TimelineProject()
        clip = project.add_clip("b.mp4", "b", duration_frames=30)
        with self.assertRaises(ValueError):
            project.set_clip_transition(clip.clip_id, dissolve_in_frames=31)

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
        self.assertEqual(project.to_dict()["schema_version"], 18)

    def test_audio_track_mixer_round_trip(self):
        project = TimelineProject()
        project.set_audio_track("A1", volume=0.65, muted=True)
        project.set_audio_track("A2", solo=True)
        restored = TimelineProject.from_dict(project.to_dict())
        self.assertAlmostEqual(restored.audio_track_settings["A1"]["volume"], 0.65)
        self.assertTrue(restored.audio_track_settings["A1"]["muted"])
        self.assertTrue(restored.audio_track_settings["A2"]["solo"])

    def test_audio_track_volume_out_of_range_is_rejected(self):
        project = TimelineProject()
        with self.assertRaises(ValueError):
            project.set_audio_track("A1", volume=2.5)
        with self.assertRaises(ValueError):
            project.set_audio_track("V1", muted=True)

    def test_audio_ducking_settings_round_trip(self):
        project = TimelineProject()
        project.set_audio_ducking(
            enabled=True, voice_track="A1", music_track="A2",
            reduction_db=16, attack_ms=35, release_ms=650,
        )
        restored = TimelineProject.from_dict(project.to_dict())
        self.assertTrue(restored.audio_ducking["enabled"])
        self.assertEqual(restored.audio_ducking["voice_track"], "A1")
        self.assertEqual(restored.audio_ducking["music_track"], "A2")
        self.assertEqual(restored.audio_ducking["reduction_db"], 16)
        self.assertEqual(restored.audio_ducking["attack_ms"], 35)
        self.assertEqual(restored.audio_ducking["release_ms"], 650)

    def test_audio_ducking_rejects_invalid_routing_and_amount(self):
        project = TimelineProject()
        with self.assertRaises(ValueError):
            project.set_audio_ducking(voice_track="A1", music_track="A1")
        with self.assertRaises(ValueError):
            project.set_audio_ducking(reduction_db=30)

    def test_legacy_projects_receive_default_track_mixer(self):
        restored = TimelineProject.from_dict({"clips": []})
        self.assertEqual(
            restored.audio_track_settings["A1"],
            {"volume": 1.0, "muted": False, "solo": False},
        )

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


    def test_anchor_and_easing_round_trip(self):
        project = TimelineProject()
        clip = project.add_clip("motion.mp4", "motion.mp4", duration_frames=90)
        clip.anchor_x = 0.2
        clip.anchor_y = 0.8
        project.set_clip_transform_keyframes(clip.clip_id, [
            {"frame": 0, "scale": 1.0, "ease": "ease_in_out"},
            {"frame": 45, "scale": 1.8, "ease": "ease_out"},
        ])
        restored = TimelineProject.from_dict(project.to_dict())
        result = restored.get_clip(clip.clip_id)
        self.assertAlmostEqual(result.anchor_x, 0.2)
        self.assertAlmostEqual(result.anchor_y, 0.8)
        self.assertEqual(result.transform_keyframes[0]["ease"], "ease_in_out")

    def test_invalid_anchor_and_easing_are_rejected(self):
        project = TimelineProject()
        clip = project.add_clip("motion.mp4", "motion.mp4", duration_frames=90)
        clip.anchor_x = 1.5
        with self.assertRaises(ValueError):
            clip.validate()
        clip.anchor_x = 0.5
        with self.assertRaises(ValueError):
            project.set_clip_transform_keyframes(clip.clip_id, [{"frame": 0, "ease": "bounce"}])

    def test_reverse_persists_and_preserves_source_range_on_split(self):
        project = TimelineProject()
        clip = project.add_clip("reverse.mp4", "reverse.mp4", duration_frames=100)
        clip.source_in = 20
        project.set_clip_reverse(clip.clip_id, True)
        left, right = project.split_clip(clip.clip_id, 40)
        self.assertEqual(left.source_in, 80)
        self.assertEqual(right.source_in, 20)
        self.assertTrue(left.reverse_playback)
        self.assertTrue(right.reverse_playback)
        restored = TimelineProject.from_dict(project.to_dict())
        self.assertTrue(restored.get_clip(clip.clip_id).reverse_playback)

    def test_reverse_trim_keeps_correct_source_side(self):
        project = TimelineProject()
        clip = project.add_clip("reverse.mp4", "reverse.mp4", duration_frames=100)
        clip.source_in = 20
        project.set_clip_reverse(clip.clip_id, True)
        project.trim_clip(clip.clip_id, new_start_frame=10, new_end_frame=80)
        self.assertEqual(clip.source_in, 40)

    def test_reverse_rejects_audio_only_clip(self):
        project = TimelineProject()
        clip = project.add_clip("voice.wav", "voice.wav", duration_frames=50, track="A1")
        with self.assertRaises(ValueError):
            project.set_clip_reverse(clip.clip_id, True)
    def test_speed_ramp_round_trip_split_and_trim(self):
        project = TimelineProject()
        clip = project.add_clip("ramp.mp4", "ramp.mp4", duration_frames=100)
        project.set_clip_speed_ramp(clip.clip_id, [
            {"frame": 0, "rate": 0.5},
            {"frame": 40, "rate": 2.0},
            {"frame": 80, "rate": 1.0},
        ])
        restored = TimelineProject.from_dict(project.to_dict())
        self.assertEqual(restored.get_clip(clip.clip_id).speed_ramp[1],
                         {"frame": 40, "rate": 2.0})
        left, right = restored.split_clip(clip.clip_id, 50)
        self.assertEqual([point["frame"] for point in left.speed_ramp], [0, 40])
        self.assertEqual([point["frame"] for point in right.speed_ramp], [0, 30])
        self.assertAlmostEqual(right.speed_ramp[0]["rate"], 1.75)
        project2 = TimelineProject()
        trimmed = project2.add_clip("ramp.mp4", "ramp.mp4", duration_frames=100)
        project2.set_clip_speed_ramp(trimmed.clip_id, [
            {"frame": 10, "rate": 0.5}, {"frame": 60, "rate": 2.0}
        ])
        project2.trim_clip(trimmed.clip_id, new_start_frame=20, new_end_frame=90)
        self.assertEqual([point["frame"] for point in trimmed.speed_ramp], [0, 40])
        self.assertAlmostEqual(trimmed.speed_ramp[0]["rate"], 0.8)

    def test_speed_ramp_rejects_invalid_rates_and_audio_clips(self):
        project = TimelineProject()
        clip = project.add_clip("ramp.mp4", "ramp.mp4", duration_frames=50)
        with self.assertRaises(ValueError):
            project.set_clip_speed_ramp(clip.clip_id, [{"frame": 0, "rate": 5.0}])
        audio = project.add_clip("voice.wav", "voice.wav", track="A1",
                                 duration_frames=50)
        with self.assertRaises(ValueError):
            project.set_clip_speed_ramp(audio.clip_id, [{"frame": 0, "rate": 1.0}])
    def test_transform_values_follow_selected_easing_curve(self):
        from timeline_model import _transform_value_at
        cases = [
            ({"frame": 0, "ease": "linear"}, 0.5),
            ({"frame": 0, "ease": "ease_in"}, 0.25),
            ({"frame": 0, "ease": "ease_out"}, 0.75),
            ({"frame": 0, "ease": "ease_in_out"}, 0.5),
            ({"frame": 0, "ease": "bezier", "bezier_y1": 0.0, "bezier_y2": 1.0}, 0.5),
        ]
        for key, expected in cases:
            with self.subTest(ease=key["ease"]):
                result = _transform_value_at([dict(key, x=0.0), {"frame": 10, "x": 1.0}], 5)
                self.assertAlmostEqual(result["x"], expected)

    def test_transform_easing_clamps_progress(self):
        from timeline_model import transform_eased_progress
        self.assertEqual(transform_eased_progress({"ease": "ease_in"}, -1), 0.0)
        self.assertEqual(transform_eased_progress({"ease": "ease_out"}, 2), 1.0)


if __name__ == "__main__":
    unittest.main()
