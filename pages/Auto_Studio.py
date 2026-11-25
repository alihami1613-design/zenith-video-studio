import json
import re
import subprocess
import tempfile
from pathlib import Path

import requests
import streamlit as st
import imageio_ffmpeg

st.set_page_config(page_title="ZENITH Auto Studio", page_icon="🎬", layout="wide")
st.title("🎬 ZENITH AUTO STUDIO")
st.caption("ZENITH BEYOND | جست‌وجوی ویدئوهای رایگان و تدوین خودکار مستند افقی")

st.info("این صفحه جدا از Documentary Editor است؛ فایل‌های قبلی و مراحل تأیید پروژه را تغییر نمی‌دهد.")

with st.expander("تنظیم اتصال Pexels", expanded=True):
    st.write("برای جست‌وجوی خودکار ویدئوهای استوک رایگان، یک API Key رایگان از Pexels لازم است. کلید فقط برای درخواست همین صفحه استفاده می‌شود.")
    try:
        saved_key = st.secrets.get("PEXELS_API_KEY", "")
    except Exception:
        saved_key = ""
    api_key = st.text_input("Pexels API Key", value=saved_key, type="password", help="در Streamlit Cloud بهتر است کلید را در App settings → Secrets با نام PEXELS_API_KEY ذخیره کنی.")

script = st.text_area(
    "متن سناریو را وارد کن؛ هر صحنه را با یک خط خالی از صحنه بعد جدا کن.",
    height=220,
    placeholder="The human brain contains billions of neurons...\n\nInside the body, the heart works continuously..."
)
narration = st.file_uploader("صدای گوینده (اختیاری؛ برای تنظیم زمان صحنه‌ها)", type=["mp3", "wav", "m4a", "aac", "ogg"])
music = st.file_uploader("موسیقی پس‌زمینه (اختیاری)", type=["mp3", "wav", "m4a", "aac", "ogg"])

scenes = [p.strip() for p in re.split(r"\n\s*\n", script) if p.strip()]
if scenes:
    st.caption(f"{len(scenes)} صحنه از متن شناسایی شد. برای نتیجه بهتر، هر صحنه یک ایده تصویری روشن داشته باشد.")

def pexels_search(query, key):
    response = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": key},
        params={"query": query[:100], "per_page": 8, "orientation": "landscape", "size": "medium"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("videos", [])

def choose_file(video):
    files = [f for f in video.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("link")]
    if not files:
        return None
    landscape = [f for f in files if (f.get("width") or 0) >= (f.get("height") or 0)]
    files = landscape or files
    files.sort(key=lambda f: (f.get("width") or 0, f.get("height") or 0))
    return files[-1]

def get_duration(ffmpeg, path):
    result = subprocess.run([ffmpeg, "-i", str(path), "-f", "null", "-"], capture_output=True, text=True, timeout=90)
    match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    if not match:
        raise ValueError("مدت فایل صوتی تشخیص داده نشد.")
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)

if "pexels_results" not in st.session_state:
    st.session_state.pexels_results = {}

if st.button("🔎 جست‌وجوی تصاویر و ویدئوهای هر صحنه", type="primary", use_container_width=True):
    if not api_key:
        st.error("ابتدا Pexels API Key را وارد کن.")
    elif not scenes:
        st.error("ابتدا متن سناریو را وارد کن و صحنه‌ها را با خط خالی جدا کن.")
    else:
        found = {}
        bar = st.progress(0)
        status = st.empty()
        try:
            for i, scene in enumerate(scenes):
                # The scene text is used as a search phrase; the user can refine it below.
                query = re.sub(r"[^\w\s-]", " ", scene, flags=re.UNICODE)
                query = " ".join(query.split()[:9]) or "documentary science technology"
                status.write(f"جست‌وجوی صحنه {i + 1} از {len(scenes)}: {query}")
                found[i] = {"query": query, "videos": pexels_search(query, api_key)}
                bar.progress((i + 1) / len(scenes))
            st.session_state.pexels_results = found
            st.session_state.pexels_scene_count = len(scenes)
            st.success("نتایج جست‌وجو آماده شد. برای هر صحنه یک ویدئو انتخاب کن.")
        except requests.HTTPError as e:
            st.error(f"خطای Pexels: {e}. کلید API و دسترسی اینترنت را بررسی کن.")
        except Exception as e:
            st.error(f"جست‌وجو انجام نشد: {e}")

results = st.session_state.pexels_results
if results and st.session_state.get("pexels_scene_count") == len(scenes):
    st.subheader("انتخاب و تأیید ویدئوی هر صحنه")
    selections = {}
    for i, scene in enumerate(scenes):
        data = results.get(i, {})
        videos = data.get("videos", [])
        with st.expander(f"صحنه {i + 1}: {scene[:90]}", expanded=(i == 0)):
            query = st.text_input("عبارت جست‌وجو (قابل ویرایش)", value=data.get("query", ""), key=f"q_{i}")
            if query != data.get("query"):
                st.caption("برای اعمال عبارت جدید، دکمه جست‌وجوی بالا را دوباره بزن.")
            if not videos:
                st.warning("برای این صحنه نتیجه‌ای پیدا نشد. عبارت جست‌وجو را ساده‌تر کن و دوباره جست‌وجو بزن.")
                continue
            labels = []
            valid = []
            for v in videos:
                vf = choose_file(v)
                if vf:
                    valid.append((v, vf))
                    labels.append(f"ویدئو {v.get('id')} — {v.get('duration', '?')} ثانیه — {vf.get('width')}×{vf.get('height')}")
            if not valid:
                st.warning("فایل MP4 مناسبی در نتایج نبود.")
                continue
            chosen = st.selectbox("ویدئوی این صحنه", range(len(valid)), format_func=lambda n: labels[n], key=f"pick_{i}")
            v, vf = valid[chosen]
            st.video(vf["link"])
            st.caption(f"منبع: Pexels | شناسه ویدئو: {v.get('id')}")
            selections[i] = {"url": vf["link"], "id": v.get("id"), "duration": v.get("duration", 0)}

    st.warning("قبل از رندر، انتخاب هر صحنه را بازبینی کن. نتایج خودکار ممکن است از نظر معنایی دقیق نباشند.")
    if st.button("✅ تأیید انتخاب‌ها و ساخت ویدئوی 1080p", type="primary", use_container_width=True):
        if len(selections) != len(scenes):
            st.error("برای همه صحنه‌ها باید یک ویدئو انتخاب شود.")
            st.stop()
        if not api_key:
            st.error("کلید Pexels موجود نیست.")
            st.stop()

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        progress = st.progress(0)
        status = st.empty()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                total_duration = get_duration(ffmpeg, work / "narration" ) if False else None
                narration_path = None
                if narration:
                    narration_path = work / f"narration.{narration.name.rsplit('.', 1)[-1]}"
                    narration_path.write_bytes(narration.getbuffer())
                    total_duration = get_duration(ffmpeg, narration_path)
                else:
                    total_duration = max(8, len(scenes) * 8)

                weights = [max(1, len(re.findall(r"\w+", s))) for s in scenes]
                weight_sum = sum(weights)
                durations = [max(2.0, total_duration * w / weight_sum) for w in weights]
                # Keep the sum exactly equal to narration duration.
                if len(durations) > 1:
                    durations[-1] = max(2.0, total_duration - sum(durations[:-1]))
                else:
                    durations[0] = total_duration

                rendered = []
                for i, scene in enumerate(scenes):
                    status.write(f"دریافت و آماده‌سازی صحنه {i + 1} از {len(scenes)}...")
                    response = requests.get(selections[i]["url"], stream=True, timeout=90)
                    response.raise_for_status()
                    clip_path = work / f"source_{i:02d}.mp4"
                    size = 0
                    with clip_path.open("wb") as out:
                        for chunk in response.iter_content(1024 * 1024):
                            if chunk:
                                size += len(chunk)
                                if size > 180 * 1024 * 1024:
                                    raise ValueError("حجم یکی از کلیپ‌ها بیشتر از ۱۸۰ مگابایت است.")
                                out.write(chunk)
                    scene_path = work / f"scene_{i:02d}.mp4"
                    subprocess.run([
                        ffmpeg, "-y", "-stream_loop", "-1", "-i", str(clip_path),
                        "-t", f"{durations[i]:.3f}",
                        "-vf", "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1,fps=30,format=yuv420p",
                        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                        "-movflags", "+faststart", str(scene_path)
                    ], check=True, capture_output=True, text=True, timeout=600)
                    rendered.append(scene_path)
                    progress.progress(int((i + 1) / (len(scenes) + 1) * 75))

                concat = work / "concat.txt"
                concat.write_text("".join(f"file '{p.as_posix()}'\n" for p in rendered), encoding="utf-8")
                silent = work / "silent.mp4"
                subprocess.run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(silent)],
                               check=True, capture_output=True, text=True, timeout=600)

                final = work / "ZENITH_BEYOND_AUTO.mp4"
                cmd = [ffmpeg, "-y", "-i", str(silent)]
                if narration_path:
                    cmd += ["-i", str(narration_path)]
                music_path = None
                if music:
                    music_path = work / f"music.{music.name.rsplit('.', 1)[-1]}"
                    music_path.write_bytes(music.getbuffer())
                    cmd += ["-stream_loop", "-1", "-i", str(music_path)]
                if narration_path and music_path:
                    cmd += ["-filter_complex", "[1:a]volume=1.0[n];[2:a]volume=0.15[m];[n][m]amix=inputs=2:duration=first:dropout_transition=2[a]",
                            "-map", "0:v", "-map", "[a]"]
                elif narration_path:
                    cmd += ["-map", "0:v", "-map", "1:a"]
                elif music_path:
                    cmd += ["-map", "0:v", "-map", "1:a", "-af", "volume=0.15"]
                else:
                    cmd += ["-map", "0:v"]
                cmd += ["-t", f"{total_duration:.3f}", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                        "-movflags", "+faststart", str(final)]
                status.write("در حال ترکیب صدا و خروجی نهایی...")
                subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=1200)
                progress.progress(100)
                status.success("ویدئوی نهایی آماده شد.")
                st.video(final.read_bytes())
                st.download_button("⬇️ دریافت ویدئوی نهایی", data=final.read_bytes(),
                                   file_name="ZENITH_BEYOND_AUTO.mp4", mime="video/mp4",
                                   use_container_width=True)
        except subprocess.CalledProcessError as e:
            st.error("رندر با خطا متوقف شد.")
            st.code((e.stderr or str(e))[-2500:])
        except Exception as e:
            st.error(f"ساخت ویدئو انجام نشد: {e}")

st.divider()
st.caption("خروجی افقی 1920×1080 و 30fps است. جست‌وجو از Pexels انجام می‌شود؛ انتخاب نهایی صحنه‌ها با تأیید توست. سرویس API رایگان است اما به کلید و محدودیت‌های حساب Pexels وابسته است.")
