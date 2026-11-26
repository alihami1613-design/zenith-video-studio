"""Tests for CPU-conscious multi-layer H.264 timeline render command generation."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from video_render import build_animated_mask_shape_expression, build_mask_shape_expression, build_video_render_command, validate_render_project


class VideoRenderTests(unittest.TestCase):
    def project(self, folder):
        first = Path(folder) / "one.mp4"
        second = Path(folder) / "two.mp4"
        first.touch()
        second.touch()
        a = SimpleNamespace(
            path=str(first), name="one", track="V1", clip_id="one",
            media_type="video", start_frame=0, source_in=30,
            duration_frames=60, end_frame=60,
            color_grade={"exposure": 1, "contrast": 1.2, "saturation": 1.1},
        )
        b = SimpleNamespace(
            path=str(second), name="two", track="V1", clip_id="two",
            media_type="video", start_frame=90, source_in=0,
            duration_frames=30, end_frame=120, color_grade={},
        )
        return SimpleNamespace(
            fps=30, width=1920, height=1080, duration_frames=120,
            clips=[a, b],
        )


    def test_animated_polygon_keyframes_build_per_vertex_expressions(self):
        from video_render import _keyframe_expression, build_animated_mask_shape_expression
        keys = [{"frame": 0, "ease": "linear", "value": 0.1},
                {"frame": 30, "ease": "linear", "value": 0.9}]
        x_expr = _keyframe_expression(keys, "value", 0.1, 30, "T")
        expression = build_animated_mask_shape_expression(
            "polygon", "0", "0", "1", "1",
            [[0.1, 0.1], [0.8, 0.1], [0.5, 0.8]],
            (0.0, 0.0, 1.0, 1.0),
            [[x_expr, x_expr], ["0.8", "0.1"], ["0.5", "0.8"]],
        )
        self.assertIn("T", expression)
        self.assertIn("0.900000", expression)

    def test_builds_keyframed_position_scale_and_rotation(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[0].transform_keyframes = [
                {"frame": 0, "x": -0.25, "y": 0.0, "scale": 1.0, "rotation": 0.0},
                {"frame": 30, "x": 0.25, "y": 0.1, "scale": 1.5, "rotation": 15.0},
            ]
            command = build_video_render_command("ffmpeg", project, "out.mp4")
        joined = " ".join(command)
        self.assertIn("scale=w='iw*(if(lt(t", joined)
        self.assertIn("rotate=angle=", joined)
        self.assertIn("overlay=x='(W-w)/2+W*", joined)
        self.assertIn("y='(H-h)/2+H*", joined)

    def test_builds_cubic_bezier_transform_easing_expression(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[0].transform_keyframes = [
                {"frame": 0, "scale": 1.0, "ease": "bezier",
                 "bezier_y1": 0.2, "bezier_y2": 0.8},
                {"frame": 30, "scale": 1.5},
            ]
            command = build_video_render_command("ffmpeg", project, "out.mp4")
        joined = " ".join(command)
        self.assertIn("0.200000", joined)
        self.assertIn("0.800000", joined)
        self.assertIn("3*(1-(min(max((t", joined)

    def test_builds_keyframed_opacity_alpha_expression(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[0].transform_keyframes = [
                {"frame": 0, "opacity": 1.0},
                {"frame": 30, "opacity": 0.25},
            ]
            command = build_video_render_command("ffmpeg", project, "out.mp4")
        joined = " ".join(command)
        self.assertIn("geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)'", joined)
        self.assertIn("a='alpha(X,Y)*(if(lt(T", joined)
        self.assertIn("0.250000", joined)

    def test_uses_lightweight_alpha_filter_for_constant_opacity(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[0].transform_keyframes = [
                {"frame": 0, "opacity": 0.5},
                {"frame": 30, "opacity": 0.5},
            ]
            command = build_video_render_command("ffmpeg", project, "out.mp4")
        joined = " ".join(command)
        self.assertIn("colorchannelmixer=aa=0.500000", joined)
        self.assertNotIn("geq=r='r(X,Y)'", joined)

    def test_chroma_key_and_rectangular_mask_filters(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            clip = project.clips[0]
            clip.chroma_key_enabled = True
            clip.chroma_key_color = "#00FF00"
            clip.chroma_key_similarity = 0.30
            clip.chroma_key_blend = 0.10
            clip.mask_enabled = True
            clip.mask_x = 0.1
            clip.mask_y = 0.2
            clip.mask_width = 0.7
            clip.mask_height = 0.6
            command = build_video_render_command("ffmpeg", project, "out.mp4")
        joined = " ".join(command)
        self.assertIn("colorkey=0x00FF00:0.3000:0.1000", joined)
        self.assertIn("crop=w='max(2\\,trunc(iw*0.700000))'", joined)
        self.assertIn("pad=1920:1080:x='trunc(1920*0.100000)':y='trunc(1080*0.200000)':color=black@0", joined)

    def test_disabled_chroma_key_and_mask_keep_render_pipeline_light(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            command = build_video_render_command("ffmpeg", project, "out.mp4")
        joined = " ".join(command)
        self.assertNotIn("colorkey=", joined)
        self.assertNotIn("crop=w=", joined)

    def test_ellipse_mask_uses_alpha_geometry_and_feather(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            clip = project.clips[0]
            clip.mask_enabled = True
            clip.mask_shape = "ellipse"
            clip.mask_x = 0.2
            clip.mask_y = 0.1
            clip.mask_width = 0.6
            clip.mask_height = 0.8
            clip.mask_feather_px = 6.0
            command = build_video_render_command("ffmpeg", project, "out.mp4")
        joined = " ".join(command)
        self.assertIn("geq=r='r(X,Y)'", joined)
        self.assertIn("lte(pow((X-960.000000)/576.000000", joined)
        self.assertIn("gblur=sigma=6.000:steps=1:planes=8", joined)
        self.assertNotIn("crop=w=", joined)

    def test_polygon_mask_expression_supports_three_to_eight_points(self):
        expression = build_mask_shape_expression(
            "polygon", 0.0, 0.0, 1.0, 1.0,
            [[0.5, 0.1], [0.9, 0.9], [0.1, 0.9]], 1920, 1080,
        )
        self.assertIn("mod(", expression)
        self.assertIn("eq(", expression)
        self.assertGreaterEqual(expression.count("if("), 2)
        with self.assertRaisesRegex(ValueError, "at least 3 points"):
            build_mask_shape_expression("polygon", 0, 0, 1, 1, [[0, 0], [1, 1]], 1920, 1080)

    def test_polygon_mask_render_filter_and_zero_feather_omit_blur(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            clip = project.clips[0]
            clip.mask_enabled = True
            clip.mask_shape = "polygon"
            clip.mask_points = [[0.5, 0.1], [0.9, 0.9], [0.1, 0.9]]
            clip.mask_feather_px = 0.0
            command = build_video_render_command("ffmpeg", project, "out.mp4")
        joined = " ".join(command)
        self.assertIn("geq=r='r(X,Y)'", joined)
        self.assertIn("mod(", joined)
        self.assertNotIn("gblur=", joined)

    def test_animated_mask_expression_uses_per_frame_bounds_for_all_shapes(self):
        bounds = ("if(lt(T\,1.000000)\,0.000000\,0.200000)",
                  "0.100000", "0.600000", "0.700000")
        for shape in ("rectangle", "ellipse", "polygon"):
            expression = build_animated_mask_shape_expression(
                shape, *bounds,
                [[0.5, 0.1], [0.9, 0.9], [0.1, 0.9]],
                (0.0, 0.0, 1.0, 1.0),
            )
            self.assertIn("T", expression)
            self.assertIn("W", expression)
            self.assertIn("H", expression)

    def test_mask_keyframes_generate_animated_geq_filter(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            clip = project.clips[0]
            clip.mask_enabled = True
            clip.mask_shape = "ellipse"
            clip.mask_keyframes = [
                {"frame": 0, "x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
                {"frame": 25, "x": 0.2, "y": 0.1, "width": 0.6, "height": 0.7},
            ]
            command = build_video_render_command("ffmpeg", project, "out.mp4")
        joined = " ".join(command)
        self.assertIn("geq=r='r(X,Y)'", joined)
        self.assertIn("T", joined)
        self.assertIn("if(lt(T\\,0.833333)", joined)
        self.assertNotIn("crop=w=", joined)

    def test_builds_alpha_aware_multiply_blend_pipeline(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[0].blend_mode = "multiply"
            command = build_video_render_command("ffmpeg", project, "out.mp4")
        joined = " ".join(command)
        self.assertIn("blend=all_mode=multiply", joined)
        self.assertIn("[topfull0]alphaextract[blendmask0]", joined)
        self.assertIn("[base0][blendraw0][blendmask0]maskedmerge[base1]", joined)

    def test_normal_blend_mode_keeps_lightweight_overlay_path(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[0].blend_mode = "normal"
            command = build_video_render_command("ffmpeg", project, "out.mp4")
        joined = " ".join(command)
        self.assertIn("[base0][v0]overlay", joined)
        self.assertNotIn("maskedmerge", joined)

    def test_builds_1080p_h264_with_grade_and_black_gap(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            command = build_video_render_command("ffmpeg", project, "out.mp4")
        joined = " ".join(command)
        self.assertIn("scale=1920:1080:force_original_aspect_ratio=decrease", joined)
        self.assertIn("color=c=black:s=1920x1080:r=30:d=4.000000", joined)
        self.assertIn("setpts=PTS+3.000000/TB", joined)
        self.assertIn("exposure=exposure=1.000", joined)
        self.assertIn("libx264", joined)
        self.assertIn("-crf 22", joined)
        self.assertIn("-threads 2", joined)
        self.assertIn("-filter_complex_threads 1", joined)
        self.assertIn("-pix_fmt yuv420p", joined)

    def test_renders_visual_fades_as_alpha_filters(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[0].video_fade_in_frames = 15
            project.clips[0].video_fade_out_frames = 30
            command = build_video_render_command("ffmpeg", project, "out.mp4")
        joined = " ".join(command)
        self.assertIn("fade=t=in:st=0:d=0.500000:alpha=1", joined)
        self.assertIn("fade=t=out:st=1.000000:d=1.000000:alpha=1", joined)

    def test_cross_dissolve_prerolls_incoming_clip_without_changing_timeline(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[1].start_frame = 60
            project.clips[1].end_frame = 90
            project.clips[1].transition_in_frames = 15
            project.clips[1].source_in = 30
            project.duration_frames = 90
            command = build_video_render_command("ffmpeg", project, "out.mp4")
        joined = " ".join(command)
        self.assertIn("fade=t=in:st=0:d=0.500000:alpha=1", joined)
        self.assertIn("trim=duration=1.500000", joined)
        self.assertIn("-ss 0.500000", joined)
        self.assertIn("setpts=PTS+1.500000/TB", joined)
        self.assertEqual(project.duration_frames, 90)

    def test_builds_wipe_left_alpha_reveal(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[1].start_frame = 60
            project.clips[1].end_frame = 90
            project.clips[1].source_in = 30
            project.clips[1].transition_in_frames = 15
            project.clips[1].transition_in_type = "wipe_left"
            project.duration_frames = 90
            command = build_video_render_command("ffmpeg", project, "out.mp4")
        joined = " ".join(command)
        self.assertIn("geq=r='r(X,Y)'", joined)
        self.assertIn("a='if(lte(X,W*min(max(T/0.500000", joined)

    def test_builds_push_left_motion_overlay(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[1].start_frame = 60
            project.clips[1].end_frame = 90
            project.clips[1].source_in = 30
            project.clips[1].transition_in_frames = 15
            project.clips[1].transition_in_type = "push_left"
            project.duration_frames = 90
            command = build_video_render_command("ffmpeg", project, "out.mp4")
        joined = " ".join(command)
        self.assertIn("overlay=x='-W+W*min(max((t-1.500000)/0.500000", joined)

    def test_rejects_cross_dissolve_without_adjacent_previous_clip(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[1].transition_in_frames = 15
            with self.assertRaisesRegex(ValueError, "چسبیده"):
                validate_render_project(project)

    def test_rejects_cross_dissolve_without_source_handles(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[1].start_frame = 60
            project.clips[1].end_frame = 90
            project.clips[1].transition_in_frames = 15
            with self.assertRaisesRegex(ValueError, "فریم‌های اضافه"):
                validate_render_project(project)

    def test_rejects_cross_dissolve_when_visual_fade_in_also_enabled(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[1].start_frame = 60
            project.clips[1].end_frame = 90
            project.clips[1].transition_in_frames = 15
            project.clips[1].video_fade_in_frames = 10
            with self.assertRaisesRegex(ValueError, "هم‌زمان"):
                validate_render_project(project)

    def test_rejects_visual_fade_longer_than_clip(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[0].video_fade_in_frames = 61
            with self.assertRaisesRegex(ValueError, "Fade تصویری"):
                validate_render_project(project)

    def test_composites_upper_track_over_lower_track(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            upper = Path(folder) / "upper.mp4"
            upper.touch()
            overlay = SimpleNamespace(
                path=str(upper), name="overlay", track="V2", clip_id="overlay",
                media_type="video", start_frame=30, source_in=0,
                duration_frames=30, end_frame=60, color_grade={},
            )
            project.clips.append(overlay)
            command = build_video_render_command("ffmpeg", project, "out.mp4")
        joined = " ".join(command)
        self.assertIn("setpts=PTS+1.000000/TB", joined)
        self.assertIn("[base1][v1]overlay", joined)
        self.assertIn("[base2][v2]overlay", joined)

    def test_allows_overlap_between_different_video_tracks(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[1].track = "V2"
            clips = validate_render_project(project)
            self.assertEqual(len(clips), 2)

    def test_rejects_overlap_on_same_track(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.clips[1].start_frame = 50
            project.clips[1].end_frame = 80
            with self.assertRaisesRegex(ValueError, "هم‌پوشانی"):
                validate_render_project(project)

    def test_still_image_is_looped_for_its_timeline_duration(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            image = Path(folder) / "still.png"
            image.touch()
            project.clips[0].path = str(image)
            project.clips[0].source_in = 0
            command = build_video_render_command("ffmpeg", project, "out.mp4")
        joined = " ".join(command)
        self.assertIn("-loop 1 -framerate 30 -t 2.000000", joined)
        self.assertIn("color=black@0", joined)

    def test_rejects_unsupported_frame_rate_and_missing_media(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            project.fps = 24
            with self.assertRaises(ValueError):
                validate_render_project(project)
            project.fps = 30
            project.clips[0].path = str(Path(folder) / "missing.mp4")
            with self.assertRaises(FileNotFoundError):
                validate_render_project(project)


    def test_easing_expression_and_anchor_offsets_are_rendered(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            clip = project.clips[0]
            clip.anchor_x = 0.25
            clip.anchor_y = 0.75
            clip.transform_keyframes = [
                {"frame": 0, "scale": 1.0, "x": 0.0, "y": 0.0, "ease": "ease_in_out"},
                {"frame": 30, "scale": 2.0, "x": 0.2, "y": -0.1, "ease": "linear"},
            ]
            command = build_video_render_command("ffmpeg", project, "out.mp4")
        joined = " ".join(command)
        self.assertIn("3-2*", joined)
        self.assertIn("0.250000-0.5", joined)
        self.assertIn("0.750000-0.5", joined)

    def test_reverse_filter_is_opt_in(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            normal = " ".join(build_video_render_command("ffmpeg", project, "normal.mp4"))
            project.clips[0].reverse_playback = True
            reverse = " ".join(build_video_render_command("ffmpeg", project, "reverse.mp4"))
        self.assertNotIn("reverse,setpts", normal)
        self.assertIn("reverse,setpts", reverse)

    def test_rotated_mask_expression_uses_inverse_rotation_for_every_shape(self):
        for shape in ("rectangle", "ellipse", "polygon"):
            expression = build_animated_mask_shape_expression(
                shape, "0.1", "0.2", "0.6", "0.5",
                [[0.2, 0.2], [0.8, 0.2], [0.5, 0.8]],
                (0.1, 0.2, 0.6, 0.5), rotation_expr="35",
            )
            self.assertIn("cos(", expression)
            self.assertIn("PI/180", expression)
            self.assertIn("sin(", expression)
            self.assertIn("PI/180", expression)

    def test_mask_rotation_is_applied_in_static_and_animated_render_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            project = self.project(folder)
            clip = project.clips[0]
            clip.mask_enabled = True
            clip.mask_shape = "rectangle"
            clip.mask_rotation = 22.5
            static_command = " ".join(build_video_render_command("ffmpeg", project, "static.mp4"))
            clip.mask_keyframes = [
                {"frame": 0, "rotation": 0.0, "x": 0.1, "y": 0.1, "width": 0.6, "height": 0.5},
                {"frame": 30, "rotation": 45.0, "x": 0.1, "y": 0.1, "width": 0.6, "height": 0.5},
            ]
            animated_command = " ".join(build_video_render_command("ffmpeg", project, "animated.mp4"))
        self.assertIn("cos(", static_command)
        self.assertNotIn("crop=w=", static_command)
        self.assertIn("cos(", animated_command)
        self.assertIn("T", animated_command)

if __name__ == "__main__":
    unittest.main()
