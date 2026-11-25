import re
import subprocess
import tempfile
from pathlib import Path

import requests
import streamlit as st
import imageio_ffmpeg

st.title("🌙 LUNAVERA — 15-Minute Sleep Video")
st.caption("تولید خودکار ویدئوی افقی خواب عمیق | Full HD 1080p | بدون تدوین دستی")
st.info("این ابزار مستقل از ZENITH Documentary Editor است و به پروژه‌های مستند دست نمی‌زند.")
st.caption("نسخه اصلاح‌شده: در نبود کلیپ جنگل، صحنه آرام جایگزین می‌شود.")

DURATION = 900
SCENES = [
    ("آسمان شب آرام", ["starry night sky video", "stars over dark sky video", "night sky stars video"],
     ["star", "stars", "night", "sky"], ["circled", "diagram", "map", "animation", "logo", "text"]),
    ("باران روی شیشه پنجره", ["rain drops on window video", "rain on window at night video", "raindrops glass video"],
     ["rain", "drop", "window", "glass"], ["satellite", "weather", "front", "forecast", "radar", "map", "label", "cira", "storm chase"]),
    ("جنگل مه‌آلود بدون جاده", ["misty forest video", "fog in forest video", "mist trees video"],
     ["forest", "fog", "mist"], ["driving", "motorway", "road", "car", "vehicle", "traffic", "dashcam", "gully", "highway"]),
]

music = st.file_uploader("فایل موسیقی یک‌ساعته LUNAVERA را بارگذاری کن", type=["mp3", "wav", "m4a", "aac", "ogg"])
st.caption("فایل MP3 یک‌ساعته‌ای را که در Audacity ساختی انتخاب کن.")

def commons_search(query):
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrnamespace": 6, "gsrsearch": query + " filetype:video",
        "gsrlimit": 15, "prop": "imageinfo",
        "iiprop": "url|extmetadata|mime|size",
    }
    r = requests.get("https://commons.wikimedia.org/w/api.php", params=params,
                     headers={"User-Agent": "LUNAVERA-Auto-Studio/1.0"}, timeout=40)
    r.raise_for_status()
    pages = r.json().get("query", {}).get("pages", {})
    out = []
    for p in pages.values():
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        url = info.get("url", "")
        mime = info.get("mime", "")
        license_name = (meta.get("LicenseShortName") or {}).get("value", "")
        if url and mime.startswith("video/") and license_name and url.lower().split("?")[0].endswith((".webm", ".ogv", ".ogg", ".mp4", ".mpeg", ".mpg")):
            out.append({
                "title": p.get("title", "").replace("File:", ""),
                "url": url,
                "page": info.get("descriptionurl", ""),
                "license": license_name,
                "description": re.sub(r"<[^>]+>", " ", (meta.get("ImageDescription") or meta.get("ObjectName") or {}).get("value", "")),
                "size": info.get("size", 0),
            })
    return out

def get_duration(ffmpeg, path):
    p = subprocess.run([ffmpeg, "-i", str(path), "-f", "null", "-"],
                       capture_output=True, text=True, timeout=90)
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", p.stderr)
    if not m:
        raise ValueError("مدت فایل موسیقی قابل تشخیص نیست.")
    h, mm, ss = m.groups()
    return int(h) * 3600 + int(mm) * 60 + float(ss)

class OversizeVideoError(Exception):
    pass

MAX_VIDEO_BYTES = 100 * 1024 * 1024

def download_video(url, path):
    # Wikimedia may temporarily throttle cloud-hosted apps (HTTP 429).
    headers = {
        "User-Agent": "LUNAVERA-Auto-Studio/1.1 (video downloader; respectful retry)",
        "Referer": "https://commons.wikimedia.org/",
        "Accept": "*/*",
    }
    last_error = None
    for attempt in range(6):
        try:
            with requests.get(url, stream=True, timeout=(45, 180),
                              headers=headers) as r:
                if r.status_code == 429 or r.status_code in (500, 502, 503, 504):
                    retry = r.headers.get("Retry-After")
                    wait = min(90, int(retry)) if retry and retry.isdigit() else min(60, 5 * (2 ** attempt))
                    last_error = requests.HTTPError(f"HTTP {r.status_code}; retrying after {wait}s")
                    if attempt < 5:
                        import time
                        time.sleep(wait)
                        continue
                r.raise_for_status()
                total = 0
                with path.open("wb") as f:
                    for chunk in r.iter_content(512 * 1024):
                        if chunk:
                            total += len(chunk)
                            if total > MAX_VIDEO_BYTES:
                                f.close()
                                path.unlink(missing_ok=True)
                                raise OversizeVideoError("حجم کلیپ از سقف ۱۰۰ مگابایت بیشتر است.")
                            f.write(chunk)
                if total == 0:
                    raise ValueError("فایل ویدئو خالی دریافت شد.")
                return
        except requests.RequestException as e:
            last_error = e
            if attempt < 5:
                import time
                time.sleep(min(60, 5 * (2 ** attempt)))
    raise RuntimeError(f"سرور Wikimedia چند بار درخواست دانلود را محدود کرد (429). آخرین خطا: {last_error}")
if not music:
    st.warning("فقط فایل موسیقی یک‌ساعته را انتخاب کن؛ بقیه مراحل خودکار انجام می‌شود.")
else:
    st.success(f"فایل انتخاب شد: {music.name}")
    if st.button("✨ ساخت خودکار ویدئوی ۱۵ دقیقه‌ای", type="primary", use_container_width=True):
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        progress = st.progress(0)
        status = st.empty()
        try:
            with tempfile.TemporaryDirectory() as td:
                work = Path(td)
                music_path = work / ("music." + music.name.rsplit(".", 1)[-1])
                music_path.write_bytes(music.getbuffer())
                audio_duration = get_duration(ffmpeg, music_path)
                if audio_duration < 3500:
                    raise ValueError(f"مدت موسیقی فقط {audio_duration/60:.1f} دقیقه است؛ فایل باید نزدیک به ۶۰ دقیقه باشد.")
                selected = []
                sources = []
                for i, (label, queries, _, _) in enumerate(SCENES):
                    status.write(f"جست‌وجوی خودکار صحنه {i+1}/3: {label}")
                    candidates = []
                    positive = SCENES[i][2]
                    negative = SCENES[i][3]
                    for q in queries:
                        found = commons_search(q)
                        for item in found:
                            title = item["title"].lower()
                            if any(word in title for word in negative):
                                continue
                            if i == 0:
                                relevant = (("star" in title or "stars" in title) and
                                            ("night" in title or "sky" in title))
                            elif i == 1:
                                relevant = ("rain" in title and
                                            ("window" in title or "glass" in title or "raindrop" in title))
                            else:
                                relevant = ("forest" in title and
                                            ("fog" in title or "mist" in title))
                            if relevant:
                                item["score"] = sum(1 for word in positive if word in title)
                                candidates.append(item)
                    # Skip files whose archive metadata already shows they exceed the server limit.
                    candidates = [x for x in candidates
                                  if not x.get("size") or x["size"] <= MAX_VIDEO_BYTES]
                    candidates.sort(key=lambda x: (-x.get("score", 0), x["size"] or 10**12))
                    if not candidates and i == 2 and selected and sources:
                        # A calm, already-downloaded scene is safer than failing the whole render
                        # when Commons has no small, clearly relevant fog-forest clip.
                        fallback_index = 1 if len(selected) > 1 else 0
                        chosen = dict(selected[fallback_index])
                        chosen["title"] = chosen["title"] + " (استفاده مجدد برای تداوم فضای آرام)"
                        selected.append(chosen)
                        sources.append(sources[fallback_index])
                        st.warning("کلیپ جنگل مه‌آلودِ مناسب زیر ۱۰۰ مگابایت پیدا نشد؛ برای تکمیل ویدئو از صحنه آرامِ بارانِ دریافت‌شده استفاده می‌شود.")
                        progress.progress((i + 1) * 12)
                        continue
                    if not candidates:
                        raise ValueError(
                            f"برای «{label}» کلیپ مرتبطِ زیر ۱۰۰ مگابایت پیدا نشد. "
                            "جست‌وجو انجام شد اما فایل سنگین انتخاب نشد."
                        )

                    # Try candidates one by one. If a file has no size metadata and proves too large
                    # during download, discard it and automatically try the next relevant clip.
                    source = work / f"source_{i}.video"
                    chosen = None
                    for candidate in candidates:
                        try:
                            status.write(f"دریافت صحنه {i+1}/3: {label} — بررسی حجم کلیپ")
                            download_video(candidate["url"], source)
                            chosen = candidate
                            break
                        except OversizeVideoError:
                            source.unlink(missing_ok=True)
                            continue
                    if chosen is None and i == 2 and selected and sources:
                        fallback_index = 1 if len(selected) > 1 else 0
                        chosen = dict(selected[fallback_index])
                        chosen["title"] = chosen["title"] + " (استفاده مجدد برای تداوم فضای آرام)"
                        selected.append(chosen)
                        sources.append(sources[fallback_index])
                        st.warning("کلیپ جنگل مه‌آلود از محدودیت حجم عبور کرد؛ از صحنه آرامِ بارانِ دریافت‌شده استفاده می‌شود.")
                        progress.progress((i + 1) * 12)
                        continue
                    if chosen is None:
                        raise ValueError(
                            f"برای «{label}» همه کلیپ‌های مرتبط از محدودیت ۱۰۰ مگابایت بزرگ‌تر بودند. "
                            "هیچ فایل سنگینی روی سرور نگه داشته نشد."
                        )
                    selected.append(chosen)
                    sources.append(source)
                    progress.progress((i + 1) * 12)

                st.write("ویدئوهای خودکار انتخاب‌شده:")
                for label, item in zip([x[0] for x in SCENES], selected):
                    st.markdown(f"- **{label}:** [{item['title']}]({item['page']}) — {item['license']}")

                # Encode a short 3-minute visual loop, then repeat it to create a 15-minute video.
                # This avoids encoding the full duration on Streamlit Cloud's limited CPU.
                status.write("مرحله ۱ از ۲: ساخت حلقه تصویری کوتاه ۳ دقیقه‌ای با کیفیت Full HD 1080p...")
                loop_video = work / "LUNAVERA_visual_loop.mp4"
                filter_parts = []
                for i in range(3):
                    filter_parts.append(
                        f"[{i}:v]scale=1920:1080:force_original_aspect_ratio=increase,"
                        f"crop=1920:1080,setsar=1,fps=24,format=yuv420p,"
                        f"trim=duration=60,setpts=PTS-STARTPTS[v{i}]"
                    )
                filter_parts.append("[v0][v1][v2]concat=n=3:v=1:a=0[v]")
                loop_cmd = [ffmpeg, "-y"]
                for source in sources:
                    loop_cmd += ["-stream_loop", "-1", "-i", str(source)]
                loop_cmd += ["-filter_complex", ";".join(filter_parts),
                             "-map", "[v]", "-an", "-c:v", "libx264",
                             "-preset", "ultrafast", "-crf", "23",
                             "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                             str(loop_video)]
                subprocess.run(loop_cmd, check=True, capture_output=True, text=True, timeout=1800)

                status.write("مرحله ۲ از ۲: تکرار حلقه تصویری و افزودن موسیقی؛ بدون رندر مجدد ویدئو...")
                final = work / "LUNAVERA_Deep_Sleep_15_Minutes.mp4"
                final_cmd = [
                    ffmpeg, "-y", "-stream_loop", "-1", "-i", str(loop_video),
                    "-i", str(music_path), "-map", "0:v:0", "-map", "1:a:0",
                    "-t", str(DURATION), "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "96k", "-af", "volume=0.85",
                    "-movflags", "+faststart", str(final)
                ]
                subprocess.run(final_cmd, check=True, capture_output=True, text=True, timeout=1800)
                progress.progress(100)
                status.success("ویدئوی ۱۵ دقیقه‌ای LUNAVERA آماده شد.")
                # Avoid loading a huge one-hour MP4 twice into server memory.
                st.info("پیش‌نمایش داخل صفحه غیرفعال است تا حافظه سرور حفظ شود. خروجی نهایی Full HD 1080p و دقیقاً ۱۵ دقیقه است.")
                with final.open("rb") as video_file:
                    st.download_button("⬇️ دریافت ویدئوی کامل LUNAVERA", data=video_file,
                                       file_name="LUNAVERA_Deep_Sleep_15_Minutes.mp4",
                                       mime="video/mp4", use_container_width=True)
        except subprocess.CalledProcessError as e:
            st.error("رندر در سرور متوقف شد؛ جزئیات فنی:")
            st.code((e.stderr or str(e))[-3000:])
        except Exception as e:
            st.error(f"ساخت ویدئو انجام نشد: {e}")

st.divider()
st.caption("ویدئوها از Wikimedia Commons انتخاب می‌شوند. پیش از انتشار، صفحه منبع و شرایط درج اعتبار هر کلیپ را بررسی کن.")
