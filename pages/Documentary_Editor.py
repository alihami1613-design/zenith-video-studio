import json
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

import imageio_ffmpeg
import requests
import streamlit as st

st.set_page_config(page_title="ZENITH Documentary Editor", page_icon="🎬", layout="wide")
st.title("🎬 ZENITH DOCUMENTARY EDITOR")
st.caption("ZENITH BEYOND | Documentary Production Studio")

st.markdown("""
<style>
.block-container {max-width: 1200px; padding-top: 1.6rem;}
div[data-testid="stFileUploader"] {border-radius: 12px;}
</style>
""", unsafe_allow_html=True)

st.markdown("### 01 — ساخت تصویر و سکانس")
mode = st.radio(
    "روش ساخت سکانس‌ها",
    ["ساخت خودکار ۱۲ سکانس تصویری", "استفاده از کلیپ‌های ویدئویی خودم"],
    horizontal=True,
)
st.info(
    "حالت خودکار، ۱۲ تصویر متفاوت و مرتبط را از Wikimedia Commons دریافت می‌کند "
    "و با حرکت نرم دوربین به ۱۲ سکانس ۵ ثانیه‌ای تبدیل می‌کند. این روش ویدئوی واقعیِ تولیدشده با مدل AI نیست؛ "
    "برای فوتیج ویدئویی واقعی، حالت دوم را انتخاب کن."
)

videos = []
if mode == "ساخت خودکار ۱۲ سکانس تصویری":
    st.success("۱۲ سکانس × ۵ ثانیه = ۶۰ ثانیه | هر سکانس تصویر مستقل و حرکت دوربین جداگانه دارد.")
    st.caption("موضوع این نسخه: HUMAN & AI — رابطه انسان و هوش مصنوعی")
else:
    videos = st.file_uploader(
        "کلیپ‌های ویدئویی را به ترتیب انتخاب کن (حداکثر ۱۲ کلیپ)",
        type=["mp4", "mov", "mkv", "avi", "webm"],
        accept_multiple_files=True,
        key="video_scenes_v2",
    )
    st.caption("برای خروجی دقیق ۶۰ ثانیه، هر کلیپ به‌صورت خودکار تا ۵ ثانیه تنظیم می‌شود.")

st.markdown("---")
st.markdown("### 02 — صدا")
narration = st.file_uploader(
    "فایل گویندگی (اختیاری)",
    type=["mp3", "wav", "m4a", "aac", "ogg"],
    key="narration_v2",
)
music = st.file_uploader(
    "موسیقی پس‌زمینه (اختیاری)",
    type=["mp3", "wav", "m4a", "aac", "ogg"],
    key="music_v2",
)
c1, c2 = st.columns(2)
with c1:
    narration_volume = st.slider("بلندی صدای گوینده", 0, 150, 100, 5)
with c2:
    music_volume = st.slider("بلندی موسیقی", 0, 50, 18, 1)

st.markdown("---")
st.markdown("### 03 — خروجی")
st.write("MP4 • Full HD 1920×1080 • 30 FPS • H.264")
create = st.button("🎬 ساخت ویدئوی ۶۰ ثانیه‌ای", type="primary", use_container_width=True)

SCENES = [
    ("human face portrait cinematic", "چهره انسان — آغاز روایت"),
    ("humanoid robot face close up", "چهره هوش مصنوعی"),
    ("person using computer artificial intelligence", "ورود AI به زندگی روزمره"),
    ("artificial neural network visualization", "شبکه‌های عصبی"),
    ("robot learning machine learning technology", "یادگیری ماشین"),
    ("artificial intelligence medical healthcare doctor", "هوش مصنوعی در پزشکی"),
    ("industrial robotics automation factory", "هوش مصنوعی در صنعت"),
    ("human robot collaboration working together", "همکاری انسان و ماشین"),
    ("future of work office automation", "آینده مشاغل"),
    ("smart city technology skyline", "شهرهای هوشمند"),
    ("human hand robotic hand interaction", "رابطه انسان و ماشین"),
    ("human silhouette digital technology sunrise", "پایان — آینده مشترک"),
]

def fetch_commons_image(query, used_titles, folder, index):
    api = "https://commons.wikimedia.org/w/api.php"
    headers = {"User-Agent": "ZENITHDocumentaryStudio/1.0 (educational video editor)"}
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": query + " filetype:bitmap",
        "gsrnamespace": 6,
        "gsrlimit": 15,
        "prop": "imageinfo",
        "iiprop": "url",
        "iiurlwidth": 1920,
        "format": "json",
    }
    response = requests.get(api, params=params, headers=headers, timeout=35)
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", {})
    candidates = sorted(pages.values(), key=lambda p: p.get("index", 999))
    for page in candidates:
        title = page.get("title", "")
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url")
        if not url or title in used_titles:
            continue
        if not url.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png", ".webp")):
            continue
        image_response = requests.get(url, headers=headers, timeout=45)
        image_response.raise_for_status()
        if len(image_response.content) < 12000:
            continue
        path = folder / f"source_{index:02d}.jpg"
        path.write_bytes(image_response.content)
        used_titles.add(title)
        return path, title, page.get("canonicalurl", "https://commons.wikimedia.org/wiki/" + quote(title.replace(" ", "_")))
    raise RuntimeError("برای این سکانس تصویر مناسبی در Wikimedia Commons پیدا نشد: " + query)

if create:
    if mode == "استفاده از کلیپ‌های ویدئویی خودم" and not videos:
        st.error("ابتدا حداقل یک کلیپ ویدئویی انتخاب کن.")
        st.stop()
    if mode == "استفاده از کلیپ‌های ویدئویی خودم" and len(videos) > 12:
        st.error("حداکثر ۱۲ کلیپ انتخاب کن.")
        st.stop()

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    progress = st.progress(0)
    status = st.empty()
    sources = []
    try:
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            scene_files = []

            if mode == "ساخت خودکار ۱۲ سکانس تصویری":
                used_titles = set()
                for i, (query, label) in enumerate(SCENES):
                    status.write(f"دریافت سکانس {i + 1} از ۱۲: {label}")
                    image_path, title, source_url = fetch_commons_image(query, used_titles, work, i)
                    clip_path = work / f"scene_{i:02d}.mp4"
                    vf = (
                        "scale=2200:1238:force_original_aspect_ratio=increase,"
                        "crop=2200:1238,"
                        "zoompan=z='min(zoom+0.0007,1.08)':"
                        "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                        "d=1:s=1920x1080:fps=30,"
                        "fade=t=in:st=0:d=0.25,fade=t=out:st=4.7:d=0.25,"
                        "setsar=1,format=yuv420p"
                    )
                    subprocess.run(
                        [ffmpeg, "-y", "-loop", "1", "-framerate", "30", "-i", str(image_path),
                         "-vf", vf, "-t", "5", "-an", "-c:v", "libx264",
                         "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                         str(clip_path)],
                        check=True, capture_output=True, text=True, timeout=180,
                    )
                    scene_files.append(clip_path)
                    sources.append({"scene": label, "commons_title": title, "source": source_url})
                    progress.progress(int((i + 1) / 12 * 75))
            else:
                for i, uploaded in enumerate(videos):
                    status.write(f"آماده‌سازی کلیپ {i + 1} از {len(videos)}")
                    input_path = work / f"uploaded_{i:02d}_{Path(uploaded.name).name}"
                    input_path.write_bytes(uploaded.getbuffer())
                    clip_path = work / f"scene_{i:02d}.mp4"
                    subprocess.run(
                        [ffmpeg, "-y", "-stream_loop", "-1", "-i", str(input_path),
                         "-t", "5", "-vf",
                         "scale=1920:1080:force_original_aspect_ratio=decrease,"
                         "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p",
                         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                         str(clip_path)],
                        check=True, capture_output=True, text=True, timeout=240,
                    )
                    scene_files.append(clip_path)
                    progress.progress(int((i + 1) / len(videos) * 65))

            concat_file = work / "concat.txt"
            concat_file.write_text(
                "".join("file '" + p.as_posix().replace("'", "'\\''") + "'\n" for p in scene_files),
                encoding="utf-8",
            )
            silent_video = work / "silent.mp4"
            subprocess.run(
                [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
                 "-c", "copy", str(silent_video)],
                check=True, capture_output=True, text=True, timeout=240,
            )
            progress.progress(82)

            final_video = work / "ZENITH_HUMAN_AND_AI_60S.mp4"
            command = [ffmpeg, "-y", "-i", str(silent_video)]
            audio_inputs = []
            if narration:
                p = work / ("narration." + narration.name.rsplit(".", 1)[-1])
                p.write_bytes(narration.getbuffer())
                command += ["-i", str(p)]
                audio_inputs.append("narration")
            if music:
                p = work / ("music." + music.name.rsplit(".", 1)[-1])
                p.write_bytes(music.getbuffer())
                command += ["-i", str(p)]
                audio_inputs.append("music")

            if narration and music:
                graph = (
                    f"[1:a]volume={narration_volume/100:.2f},apad[n];"
                    f"[2:a]volume={music_volume/100:.2f},aloop=loop=-1:size=2000000000[m];"
                    "[n][m]amix=inputs=2:duration=longest:dropout_transition=2[a]"
                )
                command += ["-filter_complex", graph, "-map", "0:v", "-map", "[a]"]
            elif narration:
                graph = f"[1:a]volume={narration_volume/100:.2f},apad[a]"
                command += ["-filter_complex", graph, "-map", "0:v", "-map", "[a]"]
            elif music:
                graph = f"[1:a]volume={music_volume/100:.2f},aloop=loop=-1:size=2000000000[a]"
                command += ["-filter_complex", graph, "-map", "0:v", "-map", "[a]"]
            else:
                command += ["-map", "0:v"]

            command += [
                "-t", "60", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", str(final_video),
            ]
            status.write("در حال رندر خروجی نهایی Full HD...")
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=1200)
            progress.progress(100)
            status.success("ویدئوی ۶۰ ثانیه‌ای آماده شد.")
            st.video(str(final_video))
            st.download_button(
                "⬇️ دریافت ویدئوی نهایی",
                data=final_video.read_bytes(),
                file_name="ZENITH_HUMAN_AND_AI_60S.mp4",
                mime="video/mp4",
                use_container_width=True,
            )
            if sources:
                with st.expander("منابع تصاویر و اعتباردهی"):
                    for item in sources:
                        st.markdown(f"- **{item['scene']}** — [{item['commons_title']}]({item['source']})")
                    st.caption("تصاویر از Wikimedia Commons دریافت شده‌اند؛ شرایط مجوز هر فایل در صفحه منبع آن درج شده است.")
    except requests.RequestException as e:
        st.error("دریافت تصویر از Wikimedia Commons ناموفق بود. اتصال اینترنت سرویس را بررسی کن.")
        st.code(str(e))
    except subprocess.TimeoutExpired:
        st.error("رندر بیش از زمان مجاز طول کشید. تعداد یا حجم کلیپ‌ها را کمتر کن.")
    except subprocess.CalledProcessError as e:
        st.error("پردازش ویدئو ناموفق بود.")
        if e.stderr:
            st.code(e.stderr[-3500:])
    except Exception as e:
        st.error(f"خطای غیرمنتظره: {e}")

st.markdown("---")
st.caption("ZENITH BEYOND — Beyond the Visible | Auto storyboard v2")
