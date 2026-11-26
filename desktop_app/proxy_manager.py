"""Smart, non-destructive proxy generation for ZENITH Desktop.

Proxies are cached outside the project and never replace or modify source media.
The first implementation targets lightweight 960px-wide H.264/MPEG-4 previews.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path


PROXY_PRESET_VERSION = "proxy-v1-960w-crf30"


def default_proxy_cache() -> Path:
    """Return a per-user cache location without writing to the source folder."""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "ZENITH" / "Proxies"
    return Path.home() / ".cache" / "zenith" / "proxies"


def proxy_cache_key(source: str | Path) -> str:
    path = Path(source).expanduser().resolve()
    stat = path.stat()
    identity = f"{path}|{stat.st_size}|{stat.st_mtime_ns}|{PROXY_PRESET_VERSION}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def proxy_path_for(source: str | Path, cache_dir: str | Path | None = None) -> Path:
    root = Path(cache_dir) if cache_dir is not None else default_proxy_cache()
    return root / f"{proxy_cache_key(source)}.mp4"


def find_ffmpeg() -> str:
    """Prefer the bundled imageio-ffmpeg binary, then a system FFmpeg."""
    try:
        import imageio_ffmpeg
        executable = imageio_ffmpeg.get_ffmpeg_exe()
        if executable and Path(executable).is_file():
            return executable
    except Exception:
        pass
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    raise RuntimeError("FFmpeg پیدا نشد؛ بسته imageio-ffmpeg یا FFmpeg لازم است.")


def _video_encoder(ffmpeg: str) -> str:
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-encoders"],
        capture_output=True, text=True, timeout=20, check=True,
    )
    listing = (result.stdout or "") + (result.stderr or "")
    if "libx264" in listing:
        return "libx264"
    if "mpeg4" in listing:
        return "mpeg4"
    raise RuntimeError("کدگذار مناسب برای ساخت Proxy در FFmpeg پیدا نشد.")


def build_proxy_command(
    ffmpeg: str, source: str | Path, destination: str | Path, encoder: str = "libx264"
) -> list[str]:
    """Build a conservative command: max 960px width, two CPU threads."""
    return [
        str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(Path(source)), "-map", "0:v:0", "-map", "0:a?",
        "-vf", "scale='min(960,iw)':-2",
        "-c:v", encoder,
        *(["-preset", "ultrafast", "-crf", "30"] if encoder == "libx264" else ["-q:v", "5"]),
        "-threads", "2", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart", "-sn", str(Path(destination)),
    ]


def create_proxy(
    source: str | Path,
    cache_dir: str | Path | None = None,
    timeout_seconds: int = 7200,
) -> Path:
    """Create or reuse a proxy. Atomic finalization prevents partial cache files."""
    source_path = Path(source).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(str(source_path))
    target = proxy_path_for(source_path, cache_dir)
    if target.is_file() and target.stat().st_size > 0:
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.stem + ".partial.mp4")
    partial.unlink(missing_ok=True)
    ffmpeg = find_ffmpeg()
    encoder = _video_encoder(ffmpeg)
    command = build_proxy_command(ffmpeg, source_path, partial, encoder)
    try:
        subprocess.run(
            command, capture_output=True, text=True,
            timeout=timeout_seconds, check=True,
        )
        if not partial.is_file() or partial.stat().st_size == 0:
            raise RuntimeError("FFmpeg خروجی Proxy معتبری تولید نکرد.")
        os.replace(partial, target)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("ساخت Proxy بیش از زمان مجاز طول کشید.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"ساخت Proxy ناموفق بود: {detail[-1200:]}") from exc
    finally:
        partial.unlink(missing_ok=True)
    return target
