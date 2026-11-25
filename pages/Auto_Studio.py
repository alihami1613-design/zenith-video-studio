import re
import subprocess
import tempfile
from pathlib import Path

import requests
import streamlit as st
import imageio_ffmpeg

st.title("🌙 LUNAVERA — 1-Hour Sleep Video")
st.caption("تولید خودکار ویدئوی افقی خواب عمیق | 720p سبک و مناسب سرور رایگان | بدون تدوین دستی")
st.info("این ابزار مستقل از ZENITH Documentary Editor است و به پروژه‌های مستند دست نمی‌زند.")

DURATION = 3600
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
                            if total > 100 * 1024 * 1024:
                                raise ValueError("یکی از ویدئوهای آرشیو بیش از ۱۰۰ مگابایت است؛ برای جلوگیری از پر شدن فضای سرور انتخاب نشد.")
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
    if st.button("✨ ساخت خودکار ویدئوی کامل یک‌ساعته", type="primary", use_container_width=True):
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
                for i, (label, queries, _, _) in enumerate(SCENES):
                    status.write(f"جست‌وجوی خودکار صحنه {i+1}/3: {label}")
                    candidates = []
                    positive = SCENES[i][2]
                    negative = SCENES[i][3]
                    for q in queries:
                        found = commons_search(q)
                        for item in found:
                            haystack = (item["title"] + " " + item.get("description", "")).lower()
                            if any(word in haystack for word in negative):
                                continue
                            if sum(1 for word in positive if word in haystack) >= 2:
                                item["score"] = sum(2 for word in positive if word in haystack)
                                candidates.append(item)
                    if not candidates:
                        raise ValueError(
                            f"برای «{label}» کلیپِ واقعاً مرتبط و امن پیدا نشد. "
                            "برای جلوگیری از انتخاب تصویر نامربوط، رندر متوقف شد؛ هیچ ویدئوی تصادفی جایگزین نمی‌شود."
                        )
                    # Relevance first; file size only breaks ties. Never select the smallest clip blindly.
                    candidates.sort(key=lambda x: (-x.get("score", 0), x["size"] or 10**12))
                    selected.append(candidates[0])
                    progress.progress((i + 1) * 8)
                st.write("ویدئوهای خودکار انتخاب‌شده:")
                for label, item in zip([x[0] for x in SCENES], selected):
                    st.markdown(f"- **{label}:** [{item['title']}]({item['page']}) — {item['license']}")
                sources = []
                for i, (label, _, _, _) in enumerate(SCENES):
                    status.write(f"دریافت صحنه {i+1}/3: {label}")
                    source = work / f"source_{i}.video"
                    download_video(selected[i]["url"], source)
                    sources.append(source)
                    progress.progress(24 + (i + 1) * 8)

                status.write("رندر یک‌مرحله‌ای ویدئوی یک‌ساعته با کیفیت 720p؛ بدون فایل‌های میانی حجیم...")
                final = work / "LUNAVERA_Deep_Sleep_1_Hour.mp4"
                filter_parts = []
                for i in range(3):
                    filter_parts.append(
                        f"[{i}:v]scale=1280:720:force_original_aspect_ratio=increase,"
                        f"crop=1280:720,setsar=1,fps=24,format=yuv420p,"
                        f"trim=duration=1200,setpts=PTS-STARTPTS[v{i}]"
                    )
                filter_parts.append("[v0][v1][v2]concat=n=3:v=1:a=0[v]")
                cmd = [ffmpeg, "-y"]
                for source in sources:
                    cmd += ["-stream_loop", "-1", "-i", str(source)]
                cmd += ["-i", str(music_path), "-filter_complex", ";".join(filter_parts),
                        "-map", "[v]", "-map", "3:a:0", "-t", str(DURATION),
                        "-c:v", "libx264", "-preset", "ultrafast",
                        "-b:v", "650k", "-maxrate", "750k", "-bufsize", "1300k",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
                        "-af", "volume=0.85", "-movflags", "+faststart", str(final)]
                subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=7200)
                progress.progress(100)
                status.success("ویدئوی یک‌ساعته LUNAVERA آماده شد.")
                # Avoid loading a huge one-hour MP4 twice into server memory.
                st.info("پیش‌نمایش داخل صفحه غیرفعال است تا حافظه سرور حفظ شود. خروجی نهایی 720p است.")
                with final.open("rb") as video_file:
                    st.download_button("⬇️ دریافت ویدئوی کامل LUNAVERA", data=video_file,
                                       file_name="LUNAVERA_Deep_Sleep_1_Hour.mp4",
                                       mime="video/mp4", use_container_width=True)
        except subprocess.CalledProcessError as e:
            st.error("رندر در سرور متوقف شد؛ جزئیات فنی:")
            st.code((e.stderr or str(e))[-3000:])
        except Exception as e:
            st.error(f"ساخت ویدئو انجام نشد: {e}")

st.divider()
st.caption("ویدئوها از Wikimedia Commons انتخاب می‌شوند. پیش از انتشار، صفحه منبع و شرایط درج اعتبار هر کلیپ را بررسی کن.")
