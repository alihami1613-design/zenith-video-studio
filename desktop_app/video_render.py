"""CPU-conscious multi-layer H.264 timeline renderer."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

from audio_render import render_audio_mix
from proxy_manager import find_ffmpeg
from video_color import build_color_filter
from speed_ramp import build_speed_segments

RENDER_VERSION = "timeline-h264-v15-polygon-overlay"
STILL_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


def _seconds(frames: int, fps: int) -> float:
    return frames / fps


def _video_clips(clips: Iterable[object]) -> list[object]:
    return sorted(
        (clip for clip in clips if str(getattr(clip, "track", "")).startswith("V")),
        key=lambda clip: (clip.track, clip.start_frame, clip.clip_id),
    )


def _is_still(clip: object) -> bool:
    return Path(clip.path).suffix.lower() in STILL_EXTENSIONS


def validate_render_project(project: object) -> list[object]:
    fps = int(project.fps)
    width, height = int(project.width), int(project.height)
    if fps not in (25, 30):
        raise ValueError("خروجی فعلاً فقط با نرخ ۲۵ یا ۳۰ فریم بر ثانیه پشتیبانی می‌شود.")
    if width < 2 or height < 2 or width % 2 or height % 2:
        raise ValueError("ابعاد خروجی باید زوج و بزرگ‌تر از صفر باشند.")
    if width > 1920 or height > 1920:
        raise ValueError("برای حفظ کارایی، خروجی این نسخه حداکثر ۱۹۲۰ پیکسل در هر ضلع است.")
    clips = _video_clips(project.clips)
    if not clips:
        raise ValueError("برای خروجی MP4 حداقل یک کلیپ تصویری روی V1 تا V4 لازم است.")
    previous_end: dict[str, int] = {}
    previous_clip: dict[str, object] = {}
    for clip in clips:
        if clip.track not in {"V1", "V2", "V3", "V4"}:
            raise ValueError(f"ترک تصویری پشتیبانی‌نشده: {clip.track}")
        if getattr(clip, "media_type", "video") != "video":
            raise ValueError(f"نوع رسانه در خروجی تصویر پشتیبانی نمی‌شود: {clip.name}")
        source = Path(clip.path).expanduser()
        if not source.is_file():
            raise FileNotFoundError(f"فایل رسانه پیدا نشد: {source}")
        if clip.start_frame < 0 or clip.source_in < 0 or clip.duration_frames < 1:
            raise ValueError(f"زمان‌بندی کلیپ معتبر نیست: {clip.name}")
        visual_fades = (int(getattr(clip, "video_fade_in_frames", 0)), int(getattr(clip, "video_fade_out_frames", 0)))
        if min(visual_fades) < 0 or max(visual_fades) > clip.duration_frames:
            raise ValueError(f"مدت Fade تصویری نامعتبر است: {clip.name}")
        transition = int(getattr(clip, "transition_in_frames", 0))
        speed_ramp = list(getattr(clip, "speed_ramp", []) or [])
        if speed_ramp:
            if _is_still(clip):
                raise ValueError(f"Speed Ramp برای عکس ثابت لازم نیست: {clip.name}")
            if bool(getattr(clip, "reverse_playback", False)):
                raise ValueError(f"Speed Ramp و Reverse هم‌زمان فعلاً پشتیبانی نمی‌شوند: {clip.name}")
            if transition:
                raise ValueError(f"برای استفاده از Speed Ramp، Cross Dissolve کلیپ را ابتدا غیرفعال کنید: {clip.name}")
        if transition:

            previous = previous_clip.get(clip.track)
            if previous is None or previous.end_frame != clip.start_frame:
                raise ValueError(f"Cross Dissolve کلیپ {clip.name} به کلیپ قبلی چسبیده در همان ترک نیاز دارد.")
            if transition > previous.duration_frames or transition > clip.duration_frames:
                raise ValueError("مدت Cross Dissolve از طول کلیپ ورودی یا خروجی بیشتر است.")
            if int(getattr(clip, "video_fade_in_frames", 0)):
                raise ValueError("برای یک کلیپ، Cross Dissolve و Video Fade In را هم‌زمان تنظیم نکنید.")
            if not _is_still(clip) and clip.source_in < transition:
                raise ValueError("برای Cross Dissolve به فریم‌های اضافه پیش از نقطه ورود منبع نیاز است؛ نقطه ورود را جلوتر ببرید.")
        if clip.start_frame < previous_end.get(clip.track, 0):
            raise ValueError(
                f"هم‌پوشانی واقعی دو کلیپ روی {clip.track} مجاز نیست؛ "
                "Cross Dissolve از تنظیم جداگانه استفاده می‌کند."
            )
        if _is_still(clip) and clip.source_in:
            raise ValueError("برای عکس ثابت، زمان ورود منبع باید صفر باشد.")
        previous_end[clip.track] = clip.end_frame
        previous_clip[clip.track] = clip
    for track in {"V1", "V2", "V3", "V4"}:
        track_clips = [clip for clip in clips if clip.track == track]
        for left, right in zip(track_clips, track_clips[1:]):
            if int(getattr(left, "transition_in_frames", 0)) + int(getattr(right, "transition_in_frames", 0)) > left.duration_frames:
                raise ValueError("دو Cross Dissolve مجاور بیش از زمان قابل استفاده کلیپ میانی هم‌پوشانی دارند.")
    if int(project.duration_frames) < 1:
        raise ValueError("تایم‌لاین خالی است.")
    if any(c.end_frame > int(project.duration_frames) for c in clips):
        raise ValueError("پایان کلیپ از طول تایم‌لاین پروژه بیشتر است.")
    return clips



def _keyframe_expression(keyframes: list[dict[str, float]], field: str, default: float, fps: int, time_expr: str = "t") -> str:
    """Build a piecewise-linear FFmpeg expression using the supplied clip-local time expression."""
    if not keyframes:
        return f"{default:.6f}"
    points = [(int(item["frame"]) / fps, float(item.get(field, default))) for item in keyframes]
    if len(points) == 1:
        return f"{points[0][1]:.6f}"
    expression = f"{points[-1][1]:.6f}"
    for index in range(len(points) - 2, -1, -1):
        t0, v0 = points[index]
        t1, v1 = points[index + 1]
        progress = f"min(max(({time_expr}-{t0:.6f})/{(t1-t0):.6f}\\,0)\\,1)"
        easing = str(keyframes[index].get("ease", "linear"))
        if easing == "ease_in":
            progress = f"({progress})*({progress})"
        elif easing == "ease_out":
            progress = f"(1-(1-({progress}))*(1-({progress})))"
        elif easing == "ease_in_out":
            progress = f"(({progress})*({progress})*(3-2*({progress})))"
        elif easing == "bezier":
            y1 = min(1.0, max(0.0, float(keyframes[index].get("bezier_y1", 0.0))))
            y2 = min(1.0, max(0.0, float(keyframes[index].get("bezier_y2", 1.0))))
            p = progress
            one = f"(1-({p}))"
            progress = f"(3*{one}*{one}*({p})*{y1:.6f}+3*{one}*({p})*({p})*{y2:.6f}+({p})*({p})*({p}))"
        linear = f"({v0:.6f}+({v1-v0:.6f})*({progress}))"
        expression = f"if(lt({time_expr}\\,{t1:.6f})\\,{linear}\\,{expression})"
    return f"if(lt({time_expr}\\,{points[0][0]:.6f})\\,{points[0][1]:.6f}\\,{expression})"


def build_mask_shape_expression(shape: str, x: float, y: float, width: float, height: float,
                                points: list[list[float]], frame_width: int,
                                frame_height: int) -> str:
    """Build a bounded FFmpeg geq condition for ellipse or polygon alpha masks."""
    if shape == "ellipse":
        cx = (x + width / 2.0) * frame_width
        cy = (y + height / 2.0) * frame_height
        rx = max(1.0, width * frame_width / 2.0)
        ry = max(1.0, height * frame_height / 2.0)
        return f"lte(pow((X-{cx:.6f})/{rx:.6f}\\,2)+pow((Y-{cy:.6f})/{ry:.6f}\\,2)\\,1)"
    if shape != "polygon" or len(points) < 3:
        raise ValueError("Mask shape needs ellipse or a polygon with at least 3 points")
    crossings = []
    for index, point in enumerate(points):
        next_point = points[(index + 1) % len(points)]
        x1, y1 = float(point[0]) * frame_width, float(point[1]) * frame_height
        x2, y2 = float(next_point[0]) * frame_width, float(next_point[1]) * frame_height
        if abs(y2 - y1) < 1e-9:
            continue
        cross_x = f"({x1:.6f}+(Y-{y1:.6f})*({x2-x1:.6f})/({y2-y1:.6f}))"
        if y1 < y2:
            crossings.append(f"if(gt(Y\\,{y1:.6f})*lte(Y\\,{y2:.6f})*lt(X\\,{cross_x})\\,1\\,0)")
        else:
            crossings.append(f"if(gt(Y\\,{y2:.6f})*lte(Y\\,{y1:.6f})*lt(X\\,{cross_x})\\,1\\,0)")
    if not crossings:
        raise ValueError("Polygon mask cannot contain only horizontal edges")
    count = "+".join(crossings)
    return f"eq(mod({count}\\,2)\\,1)"


def build_animated_mask_shape_expression(shape: str, x_expr: str, y_expr: str,
                                          width_expr: str, height_expr: str,
                                          points: list[list[float]],
                                          base_rect: tuple[float, float, float, float],
                                          point_expressions: list[list[str]] | None = None) -> str:
    """Build a per-frame alpha condition using animated normalized mask bounds."""
    if shape == "rectangle":
        return (f"gte(X\,({x_expr})*W)*lt(X\,(({x_expr})+({width_expr}))*W)*"
                f"gte(Y\,({y_expr})*H)*lt(Y\,(({y_expr})+({height_expr}))*H)")
    if shape == "ellipse":
        cx = f"(({x_expr})+({width_expr})/2)*W"
        cy = f"(({y_expr})+({height_expr})/2)*H"
        rx = f"max(1\,({width_expr})*W/2)"
        ry = f"max(1\,({height_expr})*H/2)"
        return f"lte(pow((X-{cx})/{rx}\,2)+pow((Y-{cy})/{ry}\,2)\,1)"
    if shape != "polygon" or len(points) < 3:
        raise ValueError("Animated mask requires rectangle, ellipse or a polygon with at least 3 points")
    bx, by, bw, bh = base_rect
    crossings = []
    transformed = []
    for point_index, (px, py) in enumerate(points):
        if point_expressions is not None:
            tx = f"({point_expressions[point_index][0]})*W"
            ty = f"({point_expressions[point_index][1]})*H"
        else:
            tx = f"(({x_expr})+(({float(px):.6f}-{bx:.6f})/{max(bw, 1e-9):.6f})*({width_expr}))*W"
            ty = f"(({y_expr})+(({float(py):.6f}-{by:.6f})/{max(bh, 1e-9):.6f})*({height_expr}))*H"
        transformed.append((tx, ty))
    for index, (x1, y1) in enumerate(transformed):
        x2, y2 = transformed[(index + 1) % len(transformed)]
        denominator = f"if(eq(({y2})\\,{y1})\\,0.000000001\\,(({y2})-({y1})))"
        crossings.append(f"if(gt(Y\\,{y1})*lte(Y\\,{y2})*lt(X\\,({x1}+((Y-{y1})*({x2}-{x1})/{denominator})))\\,1\\,0)")
    if not crossings:
        raise ValueError("Animated polygon mask cannot contain only horizontal edges")
    count = "+".join(crossings)
    return f"eq(mod({count}\,2)\,1)"


def build_video_render_command(ffmpeg: str, project: object,
                               output_path: str | Path) -> list[str]:
    """Composite V1-V4 bottom-to-top; still images loop for their clip duration."""
    clips = validate_render_project(project)
    fps, width, height = int(project.fps), int(project.width), int(project.height)
    duration = _seconds(int(project.duration_frames), fps)
    command = [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error"]
    for clip in clips:
        transition = int(getattr(clip, "transition_in_frames", 0))
        playback_rate = float(getattr(clip, "playback_rate", 1.0))
        clip_duration = _seconds(clip.duration_frames + transition, fps)
        ramp_points = list(getattr(clip, "speed_ramp", []) or [])
        speed_segments = build_speed_segments(clip.duration_frames, fps, ramp_points) if ramp_points else []
        source_duration = (
            sum(float(segment["source_duration_frames"]) for segment in speed_segments) / fps
            if speed_segments else clip_duration * playback_rate
        )
        if _is_still(clip):
            command.extend([
                "-loop", "1", "-framerate", str(fps),
                "-t", f"{clip_duration:.6f}",
                "-i", str(Path(clip.path).expanduser().resolve()),
            ])
        else:
            command.extend([
                "-ss", f"{_seconds(max(0, clip.source_in - round(transition * playback_rate)), fps):.6f}",
                "-i", str(Path(clip.path).expanduser().resolve()),
            ])

    filters = [
        f"color=c=black:s={width}x{height}:r={fps}:d={duration:.6f},"
        "format=rgba[base0]"
    ]
    previous = "base0"
    for index, clip in enumerate(clips):
        transition = int(getattr(clip, "transition_in_frames", 0))
        playback_rate = float(getattr(clip, "playback_rate", 1.0))
        clip_duration = _seconds(clip.duration_frames + transition, fps)
        ramp_points = list(getattr(clip, "speed_ramp", []) or [])
        speed_segments = build_speed_segments(clip.duration_frames, fps, ramp_points) if ramp_points else []
        source_duration = (
            sum(float(segment["source_duration_frames"]) for segment in speed_segments) / fps
            if speed_segments else clip_duration * playback_rate
        )
        start = _seconds(clip.start_frame - transition, fps)
        if speed_segments:
            split_labels = "".join(f"[sr{index}_{part}]" for part in range(len(speed_segments)))
            filters.append(f"[{index}:v:0]split={len(speed_segments)}{split_labels}")
            segment_outputs = []
            for part, segment in enumerate(speed_segments):
                label = f"srout{index}_{part}"
                segment_outputs.append(f"[{label}]")
                filters.append(
                    f"[sr{index}_{part}]trim=start={float(segment['source_start_frames']) / fps:.6f}:"
                    f"duration={float(segment['source_duration_frames']) / fps:.6f},"
                    f"setpts=(PTS-STARTPTS)/{float(segment['rate']):.6f}[{label}]"
                )
            ramp_label = f"speedramp{index}"
            filters.append(
                f"{''.join(segment_outputs)}concat=n={len(speed_segments)}:v=1:a=0,"
                f"fps={fps},trim=duration={_seconds(clip.duration_frames, fps):.6f},"
                f"setpts=PTS-STARTPTS[{ramp_label}]"
            )
            video_source_label = f"[{ramp_label}]"
            source_timing = f"trim=duration={_seconds(clip.duration_frames, fps):.6f},setpts=PTS-STARTPTS,"
        else:
            video_source_label = f"[{index}:v:0]"
            source_timing = (
                f"trim=duration={source_duration:.6f},"
                + ("reverse," if bool(getattr(clip, "reverse_playback", False)) else "")
                + f"setpts=(PTS-STARTPTS)/{playback_rate:.6f},"
            )
        chain = (
            f"{video_source_label}{source_timing}"

            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"format=rgba,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:"
            "color=black@0"
        )
        if bool(getattr(clip, "chroma_key_enabled", False)):
            key_color = str(getattr(clip, "chroma_key_color", "#00FF00")).lstrip("#").upper()
            similarity = float(getattr(clip, "chroma_key_similarity", 0.25))
            key_blend = float(getattr(clip, "chroma_key_blend", 0.08))
            chain += f",colorkey=0x{key_color}:{similarity:.4f}:{key_blend:.4f}"
        if bool(getattr(clip, "mask_enabled", False)):
            mask_x = float(getattr(clip, "mask_x", 0.0))
            mask_y = float(getattr(clip, "mask_y", 0.0))
            mask_w = float(getattr(clip, "mask_width", 1.0))
            mask_h = float(getattr(clip, "mask_height", 1.0))
            mask_shape = str(getattr(clip, "mask_shape", "rectangle"))
            mask_points = list(getattr(clip, "mask_points", []) or [])
            mask_keys = list(getattr(clip, "mask_keyframes", []) or [])
            if mask_keys:
                x_expr = _keyframe_expression(mask_keys, "x", mask_x, fps, "T")
                y_expr = _keyframe_expression(mask_keys, "y", mask_y, fps, "T")
                w_expr = _keyframe_expression(mask_keys, "width", mask_w, fps, "T")
                h_expr = _keyframe_expression(mask_keys, "height", mask_h, fps, "T")
                point_expressions = None
                if mask_shape == "polygon":
                    point_expressions = []
                    for point_index, fallback_point in enumerate(mask_points):
                        vertex_x = [{"frame": key["frame"], "ease": key.get("ease", "linear"),
                                     "value": key.get("points", mask_points)[point_index][0]} for key in mask_keys]
                        vertex_y = [{"frame": key["frame"], "ease": key.get("ease", "linear"),
                                     "value": key.get("points", mask_points)[point_index][1]} for key in mask_keys]
                        point_expressions.append([
                            _keyframe_expression(vertex_x, "value", fallback_point[0], fps, "T"),
                            _keyframe_expression(vertex_y, "value", fallback_point[1], fps, "T"),
                        ])
                mask_expr = build_animated_mask_shape_expression(
                    mask_shape, x_expr, y_expr, w_expr, h_expr, mask_points,
                    (mask_x, mask_y, mask_w, mask_h), point_expressions,
                )
                chain += (
                    f",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                    f"a='if({mask_expr}\,alpha(X,Y)\,0)'"
                )
            elif mask_shape == "rectangle":
                chain += (
                    f",crop=w='max(2\,trunc(iw*{mask_w:.6f}))':"
                    f"h='max(2\,trunc(ih*{mask_h:.6f}))':"
                    f"x='trunc(iw*{mask_x:.6f})':y='trunc(ih*{mask_y:.6f})',"
                    f"pad={width}:{height}:x='trunc({width}*{mask_x:.6f})':y='trunc({height}*{mask_y:.6f})':color=black@0"
                )
            else:
                mask_expr = build_mask_shape_expression(
                    mask_shape, mask_x, mask_y, mask_w, mask_h, mask_points, width, height,
                )
                chain += (
                    f",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                    f"a='if({mask_expr}\,alpha(X,Y)\,0)'"
                )
            feather = float(getattr(clip, "mask_feather_px", 0.0))
            if feather > 0.0:
                chain += f",gblur=sigma={feather:.3f}:steps=1:planes=8"
        fade_in = int(getattr(clip, "video_fade_in_frames", 0))
        fade_out = int(getattr(clip, "video_fade_out_frames", 0))
        transition_type = str(getattr(clip, "transition_in_type", "dissolve"))
        if transition and transition_type == "dissolve":
            chain += f",fade=t=in:st=0:d={_seconds(transition, fps):.6f}:alpha=1"
        elif transition and transition_type == "wipe_left":
            transition_seconds = _seconds(transition, fps)
            chain += (
                ",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                f"a='if(lte(X,W*min(max(T/{transition_seconds:.6f}\\,0)\\,1))\\,255\\,0)'"
            )
        elif fade_in:
            chain += f",fade=t=in:st=0:d={_seconds(fade_in, fps):.6f}:alpha=1"
        if fade_out:
            fade_start = clip_duration - _seconds(fade_out, fps)
            chain += f",fade=t=out:st={fade_start:.6f}:d={_seconds(fade_out, fps):.6f}:alpha=1"
        keyframes = list(getattr(clip, "transform_keyframes", []) or [])
        if keyframes:
            opacity_values = [float(item.get("opacity", 1.0)) for item in keyframes]
            if any(abs(value - 1.0) > 1e-9 for value in opacity_values):
                if max(opacity_values) - min(opacity_values) <= 1e-9:
                    chain += f",colorchannelmixer=aa={opacity_values[0]:.6f}"
                else:
                    opacity_expr = _keyframe_expression(keyframes, "opacity", 1.0, fps, "T")
                    chain += (
                        ",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                        f"a='alpha(X,Y)*({opacity_expr})'"
                    )
        chain += f",setpts=PTS+{start:.6f}/TB"
        if keyframes:
            scale_expr = _keyframe_expression(keyframes, "scale", 1.0, fps)
            rotation_expr = _keyframe_expression(keyframes, "rotation", 0.0, fps)
            chain += (
                f",scale=w='iw*({scale_expr})':h='ih*({scale_expr})':eval=frame"
                f",rotate=angle='({rotation_expr})*PI/180':"
                "ow=rotw(iw):oh=roth(ih):c=black@0"
            )
        grade = build_color_filter(getattr(clip, "color_grade", {}))
        if grade:
            chain += "," + grade
        if bool(getattr(clip, "motion_blur", False)):
            chain += ",tmix=frames=3:weights='1 2 1'"
        chain += f"[v{index}]"
        filters.append(chain)
        out_label = f"base{index + 1}"
        if keyframes:
            clip_time = f"(t-{start:.6f})"
            x_expr = _keyframe_expression(keyframes, "x", 0.0, fps, clip_time)
            y_expr = _keyframe_expression(keyframes, "y", 0.0, fps, clip_time)
            overlay_filter = (
                f"[{previous}][v{index}]overlay="
                f"x='(W-w)/2+W*({x_expr})+W*(1-({scale_expr}))*({float(getattr(clip, 'anchor_x', 0.5)):.6f}-0.5)':"
                f"y='(H-h)/2+H*({y_expr})+H*(1-({scale_expr}))*({float(getattr(clip, 'anchor_y', 0.5)):.6f}-0.5)':"
                "eof_action=pass:repeatlast=0:shortest=0:format=auto"
            )
        elif transition and transition_type == "push_left":
            transition_seconds = _seconds(transition, fps)
            overlay_x = (
                f"x='-W+W*min(max((t-{start:.6f})/{transition_seconds:.6f}\\,0)\\,1)'"
            )
            overlay_filter = (
                f"[{previous}][v{index}]overlay={overlay_x}:y=0:"
                "eof_action=pass:repeatlast=0:shortest=0:format=auto"
            )
        else:
            overlay_filter = (
                f"[{previous}][v{index}]overlay=0:0:"
                "eof_action=pass:repeatlast=0:shortest=0:format=auto"
            )
        blend_mode = str(getattr(clip, "blend_mode", "normal"))
        if blend_mode == "normal":
            filters.append(f"{overlay_filter}[{out_label}]")
        else:
            if keyframes:
                placement_x = (
                    f"(W-w)/2+W*({x_expr})+W*(1-({scale_expr}))*"
                    f"({float(getattr(clip, 'anchor_x', 0.5)):.6f}-0.5)"
                )
                placement_y = (
                    f"(H-h)/2+H*({y_expr})+H*(1-({scale_expr}))*"
                    f"({float(getattr(clip, 'anchor_y', 0.5)):.6f}-0.5)"
                )
            elif transition and transition_type == "push_left":
                transition_seconds = _seconds(transition, fps)
                placement_x = (
                    f"-W+W*min(max((t-{start:.6f})/{transition_seconds:.6f}\\,0)\\,1)"
                )
                placement_y = "0"
            else:
                placement_x, placement_y = "0", "0"
            blend_bg = f"blendbg{index}"
            top_full = f"topfull{index}"
            blend_raw = f"blendraw{index}"
            blend_mask = f"blendmask{index}"
            filters.append(
                f"color=c=black@0:s={width}x{height}:r={fps}:d={duration:.6f},"
                f"format=rgba[{blend_bg}]"
            )
            filters.append(
                f"[{blend_bg}][v{index}]overlay=x='{placement_x}':y='{placement_y}':"
                f"eof_action=pass:repeatlast=0:shortest=0:format=auto[{top_full}]"
            )
            filters.append(
                f"[{previous}][{top_full}]blend=all_mode={blend_mode}:"
                f"eof_action=pass:repeatlast=0:shortest=0[{blend_raw}]"
            )
            filters.append(f"[{top_full}]alphaextract[{blend_mask}]")
            filters.append(
                f"[{previous}][{blend_raw}][{blend_mask}]maskedmerge[{out_label}]"
            )
        previous = out_label

    command.extend([
        "-filter_complex_threads", "1",
        "-filter_complex", ";".join(filters),
        "-map", f"[{previous}]",
        "-an", "-t", f"{duration:.6f}",
        "-r", str(fps), "-c:v", "libx264", "-preset", "ultrafast",
        "-crf", "22", "-threads", "2", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", "-sn", str(Path(output_path)),
    ])
    return command


def _run(command: list[str], timeout_seconds: int, description: str) -> None:
    try:
        subprocess.run(command, capture_output=True, text=True,
                       timeout=timeout_seconds, check=True)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{description}: زمان مجاز رندر تمام شد.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"{description}: {(detail[-1400:] or 'خطای ناشناخته FFmpeg')}") from exc


def render_timeline_mp4(project: object, output_path: str | Path,
                        timeout_seconds: int = 14400) -> Path:
    """Render multi-layer picture timeline and optional mixed audio atomically."""
    validate_render_project(project)
    target = Path(output_path).expanduser().resolve()
    if target.suffix.lower() != ".mp4":
        target = target.with_suffix(".mp4")
    target.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_ffmpeg()
    has_audio = any(
        getattr(c, "media_type", "") == "audio"
        or (getattr(c, "media_type", "") == "video"
            and getattr(c, "has_audio", False)
            and not _is_still(c))
        for c in project.clips
    )
    with tempfile.TemporaryDirectory(prefix="zenith_render_", dir=str(target.parent)) as work:
        work_dir = Path(work)
        silent_video = work_dir / "picture.mp4"
        _run(build_video_render_command(ffmpeg, project, silent_video),
             timeout_seconds, "رندر تصویر ناموفق بود")
        if not silent_video.is_file() or silent_video.stat().st_size <= 0:
            raise RuntimeError("FFmpeg فایل ویدیویی معتبر تولید نکرد.")

        partial = target.with_name(target.stem + ".partial.mp4")
        partial.unlink(missing_ok=True)
        try:
            if has_audio:
                mixed_audio = work_dir / "mix.wav"
                render_audio_mix(
                    project.clips, project.fps, mixed_audio,
                    timeline_duration_frames=project.duration_frames,
                    audio_track_settings=project.audio_track_settings,
                    audio_ducking=project.audio_ducking,
                    timeout_seconds=timeout_seconds,
                )
                mux = [
                    ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(silent_video), "-i", str(mixed_audio),
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-t", f"{_seconds(project.duration_frames, project.fps):.6f}",
                    "-movflags", "+faststart", str(partial),
                ]
                _run(mux, timeout_seconds, "ترکیب تصویر و صدا ناموفق بود")
            else:
                os.replace(silent_video, partial)
            if not partial.is_file() or partial.stat().st_size <= 0:
                raise RuntimeError("فایل MP4 خروجی معتبر ساخته نشد.")
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)
    return target
