import re
import subprocess
import tempfile
from pathlib import Path

import requests
import streamlit as st
import imageio_ffmpeg

st.set_page_config(page_title="ZENITH Auto Studio", page_icon="🎬", layout="wide")
st.title("🎬 ZENITH AUTO STUDIO")
st.caption("ZENITH BEYOND | جست‌وجو و تدوین خودکار ویدئوهای علمی و فضایی")
st.info("این صفحه مستقل از Documentary Editor است؛ پروژه‌ها و مراحل تأییدشده قبلی را تغییر نمی‌دهد.")
st.warning("منبع فعلی آرشیو NASA است؛ برای موضوعات علمی، فضایی، زمین و فناوری مناسب است و جایگزین عمومی Pexels برای همه موضوعات نیست.")

script = st.text_area(
    "متن سناریو را وارد کن؛ هر صحنه را با یک خط خالی جدا کن.",
    height=220,
    placeholder="The James Webb Space Telescope observes distant galaxies...\n\nScientists study the atmosphere of Mars..."
)
narration = st.file_uploader("صدای گوینده (اختیاری؛ برای تنظیم زمان صحنه‌ها)", type=["mp3", "wav", "m4a", "aac", "ogg"])
music = st.file_uploader("موسیقی پس‌زمینه (اختیاری)", type=["mp3", "wav", "m4a", "aac", "ogg"])
scenes = [p.strip() for p in re.split(r"\n\s*\n", script) if p.strip()]

def nasa_search(query):
    response = requests.get(
        "https://images-api.nasa.gov/search",
        params={"q": query[:100], "media_type": "video", "page_size": 8},
        timeout=30,
    )
    response.raise_for_status()
    items = response.json().get("collection", {}).get("items", [])
    videos = []
    for item in items:
        data = (item.get("data") or [{}])[0]
        nasa_id = data.get("nasa_id")
        if not nasa_id:
            continue
        manifest_response = requests.get(f"https://images-api.nasa.gov/asset/{nasa_id}", timeout=30)
        if not manifest_response.ok:
            continue
        manifest = manifest_response.json()
        files = manifest.get("collection", {}).get("items", [])
        mp4s = [x.get("href", "") for x in files if x.get("href", "").lower().split("?")[0].endswith(".mp4")]
        if mp4s:
            videos.append({
                "id": nasa_id,
                "title": data.get("title", nasa_id),
                "description": data.get("description", ""),
                "url": mp4s[0],
                "date": data.get("date_created", ""),
            })
    return videos

def get_duration(ffmpeg, path):
    result = subprocess.run([ffmpeg, "-i", str(path), "-f", "null", "-"], capture_output=True, text=True, timeout=90)
    match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    if not match:
        raise ValueError("مدت فایل صوتی تشخیص داده نشد.")
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)

if "nasa_results" not in st.session_state:
    st.session_state.nasa_results = {}

if st.button("🔎 جست‌وجوی ویدئوهای هر صحنه", type="primary", use_container_width=True):
    if not scenes:
        st.error("ابتدا متن سناریو را وارد کن و صحنه‌ها را با یک خط خالی جدا کن.")
    else:
        found = {}
        bar = st.progress(0)
        status = st.empty()
        try:
            for i, scene in enumerate(scenes):
                query = re.sub(r"[^\w\s-]", " ", scene, flags=re.UNICODE)
                query = " ".join(query.split()[:9]) or "NASA science space"
                status.write(f"جست‌وجوی صحنه {i + 1} از {len(scenes)}: {query}")
                found[i] = {"query": query, "videos": nasa_search(query)}
                bar.progress((i + 1) / len(scenes))
            st.session_state.nasa_results = found
            st.session_state.nasa_scene_count = len(scenes)
            st.success("جست‌وجو تمام شد. ویدئوی هر صحنه را بازبینی و انتخاب کن.")
        except Exception as e:
            st.error(f"جست‌وجو انجام نشد: {e}")

results = st.session_state.nasa_results
if results and st.session_state.get("nasa_scene_count") == len(scenes):
    st.subheader("انتخاب و تأیید ویدئوی هر صحنه")
    selections = {}
    for i, scene in enumerate(scenes):
        data = results.get(i, {})
        videos = data.get("videos", [])
        with st.expander(f"صحنه {i + 1}: {scene[:90]}", expanded=(i == 0)):
            st.caption(f"عبارت جست‌وجو: {data.get('query', '')}")
            if not videos:
                st.warning("برای این صحنه ویدئوی مناسبی در آرشیو NASA پیدا نشد. عبارت را علمی‌تر یا کوتاه‌تر کن.")
                continue
            labels = [f"{v['title']} | {v.get('date', '')[:10]}" for v in videos]
            chosen = st.selectbox("ویدئوی این صحنه", range(len(videos)), format_func=lambda n: labels[n], key=f"nasa_pick_{i}")
            v = videos[chosen]
            st.video(v["url"])
            st.caption(f"منبع: NASA Image and Video Library | شناسه: {v['id']}")
            selections[i] = v

    st.warning("پیش از رندر، همه انتخاب‌ها را بازبینی کن. پوشش آرشیو NASA محدود به محتوای موجود در مجموعه خودش است.")
    if st.button("✅ تأیید انتخاب‌ها و ساخت ویدئوی 1080p", type="primary", use_container_width=True):
        if len(selections) != len(scenes):
            st.error("برای همه صحنه‌ها باید یک ویدئو انتخاب شود.")
            st.stop()

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        progress = st.progress(0)
        status = st.empty()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                narration_path = None
                if narration:
                    narration_path = work / f"narration.{narration.name.rsplit('.', 1)[-1]}"
                    narration_path.write_bytes(narration.getbuffer())
                    total_duration = get_duration(ffmpeg, narration_path)
                else:
                    total_duration = max(8.0, len(scenes) * 8.0)

                weights = [max(1, len(re.findall(r"\w+", s))) for s in scenes]
                weight_sum = sum(weights)
                durations = [total_duration * w / weight_sum for w in weights]

                rendered = []
                for i in range(len(scenes)):
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
                narration_index = None
                music_index = None
                if narration_path:
                    narration_index = 1
                    cmd += ["-i", str(narration_path)]
                music_path = None
                if music:
                    music_path = work / f"music.{music.name.rsplit('.', 1)[-1]}"
                    music_path.write_bytes(music.getbuffer())
                    music_index = 2 if narration_path else 1
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
                video_bytes = final.read_bytes()
                st.video(video_bytes)
                st.download_button("⬇️ دریافت ویدئوی نهایی", data=video_bytes,
                                   file_name="ZENITH_BEYOND_AUTO.mp4", mime="video/mp4",
                                   use_container_width=True)
        except subprocess.CalledProcessError as e:
            st.error("رندر با خطا متوقف شد.")
            st.code((e.stderr or str(e))[-2500:])
        except Exception as e:
            st.error(f"ساخت ویدئو انجام نشد: {e}")

st.divider()
st.caption("خروجی افقی 1920×1080 و 30fps است. جست‌وجو از NASA Image and Video Library انجام می‌شود؛ انتخاب نهایی صحنه‌ها با تأیید توست. پیش از انتشار، اطلاعات حقوق استفاده و اعتبار هر فایل را بررسی کن.")
