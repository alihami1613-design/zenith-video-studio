import re
import subprocess
import tempfile
from pathlib import Path

import requests
import streamlit as st
import imageio_ffmpeg

st.title("🌙 LUNAVERA — 1-Hour Sleep Video")
st.caption("تولید خودکار ویدئوی افقی خواب عمیق | 1920×1080 | بدون تدوین دستی")
st.info("این ابزار مستقل از ZENITH Documentary Editor است و به پروژه‌های مستند دست نمی‌زند.")

DURATION = 3600
SCENES = [
    ("آسمان شب پرستاره", ["starry night sky", "stars night sky", "night sky"]),
    ("باران آرام شبانه", ["rain at night", "rain window", "falling rain"]),
    ("جنگل مه‌آلود آرام", ["misty forest", "fog forest", "forest fog"]),
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
                            if total > 250 * 1024 * 1024:
                                raise ValueError("یکی از ویدئوهای آرشیو بیش از ۲۵۰ مگابایت است.")
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
                for i, (label, queries) in enumerate(SCENES):
                    status.write(f"جست‌وجوی خودکار صحنه {i+1}/3: {label}")
                    candidates = []
                    for q in queries:
                        candidates = commons_search(q)
                        if candidates:
                            break
                    if not candidates:
                        raise ValueError(f"برای «{label}» ویدئوی دارای مجوز در Wikimedia Commons پیدا نشد. این بار دوباره اجرا کن.")
                    candidates.sort(key=lambda x: (x["size"] or 10**12))
                    selected.append(candidates[0])
                    progress.progress((i + 1) * 8)
                st.write("ویدئوهای خودکار انتخاب‌شده:")
                for label, item in zip([x[0] for x in SCENES], selected):
                    st.markdown(f"- **{label}:** [{item['title']}]({item['page']}) — {item['license']}")
                rendered = []
                for i, (label, _) in enumerate(SCENES):
                    status.write(f"آماده‌سازی صحنه {i+1}/3: {label}")
                    source = work / f"source_{i}.video"
                    download_video(selected[i]["url"], source)
                    out = work / f"scene_{i}.mp4"
                    subprocess.run([
                        ffmpeg, "-y", "-stream_loop", "-1", "-i", str(source),
                        "-t", "1200",
                        "-vf", "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1,fps=24,format=yuv420p",
                        "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "27",
                        "-pix_fmt", "yuv420p", str(out)
                    ], check=True, capture_output=True, text=True, timeout=1800)
                    rendered.append(out)
                    progress.progress(8 + (i + 1) * 25)
                concat = work / "concat.txt"
                concat.write_text("".join(f"file '{p.as_posix()}'\n" for p in rendered), encoding="utf-8")
                silent = work / "visuals.mp4"
                subprocess.run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
                                "-c", "copy", str(silent)], check=True, capture_output=True, text=True, timeout=300)
                final = work / "LUNAVERA_Deep_Sleep_1_Hour.mp4"
                status.write("ترکیب موسیقی و آماده‌سازی خروجی نهایی یک‌ساعته...")
                subprocess.run([
                    ffmpeg, "-y", "-i", str(silent), "-i", str(music_path),
                    "-t", str(DURATION), "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-af", "volume=0.85", "-movflags", "+faststart", str(final)
                ], check=True, capture_output=True, text=True, timeout=1200)
                progress.progress(100)
                status.success("ویدئوی یک‌ساعته LUNAVERA آماده شد.")
                # Avoid loading a huge one-hour MP4 twice into server memory.
                st.info("پیش‌نمایش داخل صفحه غیرفعال است تا سرور هنگام بارگذاری ویدئوی حجیم از کار نیفتد.")
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
