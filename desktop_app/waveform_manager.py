"""Cached low-resolution audio waveform envelopes for the ZENITH timeline."""
from __future__ import annotations

import array
import hashlib
import os
import shutil
import subprocess
from pathlib import Path


WAVEFORM_PRESET_VERSION = "waveform-v2-500hz-peak25"


def default_waveform_cache() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "ZENITH" / "Waveforms"
    return Path.home() / ".cache" / "zenith" / "waveforms"


def waveform_cache_path(source: str | Path, cache_dir: str | Path | None = None) -> Path:
    path = Path(source).expanduser().resolve()
    stat = path.stat()
    identity = f"{path}|{stat.st_size}|{stat.st_mtime_ns}|{WAVEFORM_PRESET_VERSION}"
    key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    root = Path(cache_dir) if cache_dir is not None else default_waveform_cache()
    return root / f"{key}.f32"


def find_ffmpeg() -> str:
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
    raise RuntimeError("FFmpeg برای ساخت شکل موج پیدا نشد.")


def peak_envelope(raw_pcm: bytes, samples_per_bucket: int = 5) -> list[float]:
    """Convert mono float32 PCM to normalized peak values (20 points/sec)."""
    usable = len(raw_pcm) - (len(raw_pcm) % 4)
    samples = array.array("f")
    samples.frombytes(raw_pcm[:usable])
    if not samples:
        return []
    result = []
    for offset in range(0, len(samples), max(1, samples_per_bucket)):
        chunk = samples[offset:offset + max(1, samples_per_bucket)]
        peak = max((abs(value) for value in chunk), default=0.0)
        result.append(min(1.0, max(0.0, peak)))
    return result


def create_waveform(
    source: str | Path,
    cache_dir: str | Path | None = None,
    timeout_seconds: int = 7200,
) -> Path:
    """Extract a tiny mono envelope in a worker; cache is never inside source folder."""
    source_path = Path(source).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(str(source_path))
    target = waveform_cache_path(source_path, cache_dir)
    if target.is_file() and target.stat().st_size > 0:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".partial")
    partial.unlink(missing_ok=True)
    ffmpeg = find_ffmpeg()
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(source_path),
        "-vn", "-ac", "1", "-ar", "500", "-threads", "1",
        "-f", "f32le", "pipe:1",
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=timeout_seconds, check=True,
        )
        envelope = peak_envelope(completed.stdout, samples_per_bucket=25)
        if not envelope:
            raise RuntimeError("از فایل صوتی نمونه‌ای برای نمایش شکل موج دریافت نشد.")
        packed = array.array("f", envelope)
        with partial.open("wb") as handle:
            packed.tofile(handle)
        os.replace(partial, target)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("استخراج شکل موج بیش از زمان مجاز طول کشید.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"استخراج شکل موج ناموفق بود: {detail[-1000:]}") from exc
    finally:
        partial.unlink(missing_ok=True)
    return target


def load_waveform(path: str | Path) -> list[float]:
    """Read cached float32 peak values; tolerate missing or truncated cache files."""
    source = Path(path)
    if not source.is_file():
        return []
    values = array.array("f")
    with source.open("rb") as handle:
        values.fromfile(handle, source.stat().st_size // 4)
    return [min(1.0, max(0.0, float(value))) for value in values]
