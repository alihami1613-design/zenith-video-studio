import json
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

import imageio_ffmpeg
import requests
from PIL import Image, ImageDraw, ImageFilter
import numpy as np
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
    "حالت خودکار از گرافیک‌های سینمایی یکپارچه و اختصاصی استفاده می‌کند؛ "
    "بدون عکس‌های تصادفی اینترنتی، برش ناخواسته یا زوم آزاردهنده. "
    "برای فوتیج واقعی، حالت دوم را انتخاب کن."
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

def make_scene_art(index, label, folder):
    """Create a consistent 1080p cinematic motion-graphics plate; no external stock photos."""
    W, H = 1920, 1080
    # Vectorized deep-navy gradient for fast rendering on the cloud server.
    yy, xx = np.mgrid[0:H, 0:W]
    glow = np.clip(1 - np.sqrt(((xx - 1370) / 1150) ** 2 + ((yy - 430) / 850) ** 2), 0, 1)
    t = yy / H
    arr = np.stack([
        5 + 5 * glow,
        10 + 34 * glow + 4 * t,
        22 + 43 * glow + 8 * t,
    ], axis=-1).clip(0,255).astype(np.uint8)
    img = Image.fromarray(arr, "RGB")
    d = ImageDraw.Draw(img, "RGBA")
    # Fine technical grid and framing.
    for x in range(80, W, 80):
        d.line((x, 0, x, H), fill=(105, 180, 205, 17), width=1)
    for y in range(80, H, 80):
        d.line((0, y, W, y), fill=(105, 180, 205, 17), width=1)
    d.rounded_rectangle((64, 58, W-64, H-58), radius=26, outline=(150, 205, 220, 65), width=2)
    # Abstract focal artwork varies by chapter, while retaining the same visual language.
    cx, cy = 1210, 500
    teal, cyan, gold = (60, 220, 210, 220), (95, 175, 255, 210), (230, 190, 115, 220)
    if index in (0, 1, 7, 10):
        # Human / machine profile motif.
        d.ellipse((cx-220, cy-250, cx+220, cy+190), outline=cyan if index in (1,10) else teal, width=5)
        d.arc((cx-150, cy-180, cx+150, cy+180), 205, 520, fill=gold, width=7)
        d.ellipse((cx-70, cy-55, cx-48, cy-33), fill=gold)
        d.arc((cx-80, cy-10, cx+110, cy+135), 15, 155, fill=teal, width=5)
        for k in range(9):
            yy = cy-200+k*48
            d.line((cx+250, yy, cx+360, yy), fill=(90,180,220,100), width=2)
    elif index in (3, 4):
        # Neural network: clean nodes and deliberate connections.
        layers = [[(cx-330, cy-180+i*90) for i in range(5)],
                  [(cx-100, cy-230+i*76) for i in range(7)],
                  [(cx+150, cy-180+i*90) for i in range(5)],
                  [(cx+360, cy-100+i*100) for i in range(3)]]
        for left, right in zip(layers, layers[1:]):
            for p in left:
                for q in right:
                    d.line((p, q), fill=(70,175,220,75), width=3)
        for li, layer in enumerate(layers):
            for j, (x,y) in enumerate(layer):
                r = 15 if li in (0,3) else 19
                d.ellipse((x-r,y-r,x+r,y+r), fill=gold if (j+li)%4==0 else cyan, outline=(220,245,255,220), width=2)
    elif index in (5,):
        # Medical scan / diagnostic rings.
        for r in (95,155,215,275):
            d.ellipse((cx-r,cy-r,cx+r,cy+r), outline=(70,190,220,150), width=3)
        d.line((cx-300,cy,cx+300,cy), fill=teal, width=4)
        d.line((cx,cy-300,cx,cy+300), fill=teal, width=4)
        d.polygon([(cx,cy-110),(cx+28,cy-25),(cx+115,cy),(cx+28,cy+25),(cx,cy+110),(cx-28,cy+25),(cx-115,cy),(cx-28,cy-25)], outline=gold)
    elif index in (6,):
        # Industrial robotic arm.
        pts=[(cx-240,cy+210),(cx-110,cy+60),(cx+30,cy+110),(cx+190,cy-120),(cx+300,cy-190)]
        d.line(pts, fill=cyan, width=38, joint="curve")
        for x,y in pts:
            d.ellipse((x-34,y-34,x+34,y+34), fill=(12,35,58,255), outline=gold, width=8)
        d.line((cx+300,cy-190,cx+390,cy-270), fill=gold, width=16)
    elif index in (8,):
        # Future of work: modular connected panels.
        for row in range(3):
            for col in range(4):
                x=cx-330+col*175; y=cy-190+row*155
                d.rounded_rectangle((x,y,x+125,y+105), radius=15, outline=cyan if (row+col)%2 else gold, width=4)
                d.line((x+25,y+72,x+95,y+72), fill=(140,210,230,160), width=4)
    elif index in (9,):
        # Smart city skyline.
        for j in range(9):
            x=cx-390+j*95; h=180+(j*73)%260
            d.rectangle((x,cy+220-h,x+65,cy+220), outline=cyan, width=4, fill=(15,38,62,170))
            for wy in range(cy+245-h,cy+190,48):
                d.line((x+16,wy,x+49,wy), fill=gold, width=4)
        d.arc((cx-420,cy-340,cx+420,cy+500), 195, 345, fill=teal, width=4)
    else:
        # Connected human-AI future motif.
        d.ellipse((cx-260,cy-250,cx+260,cy+270), outline=teal, width=5)
        for j in range(24):
            import math
            ang = j * math.pi / 12
            x = cx + int(220*math.cos(ang)); y=cy+int(220*math.sin(ang))
            d.ellipse((x-9,y-9,x+9,y+9), fill=gold)
            d.line((cx,cy,x,y), fill=(70,180,220,70), width=2)
    # Restrained title treatment and chapter marker.
    d.text((125, 170), "ZENITH BEYOND", fill=(205,220,228,210), stroke_width=0)
    d.text((125, 270), f"{index+1:02d} / 12", fill=(225,190,120,235))
    english_titles = [
        "THE HUMAN MIND", "THE MACHINE", "AI IN DAILY LIFE", "NEURAL NETWORKS",
        "MACHINE LEARNING", "AI IN MEDICINE", "INTELLIGENT INDUSTRY",
        "HUMAN + MACHINE", "THE FUTURE OF WORK", "SMART CITIES",
        "A NEW CONNECTION", "A SHARED FUTURE"
    ]
    d.text((125, 355), english_titles[index], fill=(240,245,248,245), stroke_width=0)
    d.line((125, 420, 510, 420), fill=(80,205,205,210), width=4)
    d.text((125, 470), "HUMAN  ×  ARTIFICIAL INTELLIGENCE", fill=(150,185,205,210))
    # Soft vignette, not a zoom or crop.
    vignette = Image.new("L", (W,H), 0)
    vd = ImageDraw.Draw(vignette)
    vd.ellipse((-300,-250,W+300,H+250), fill=215)
    vignette = vignette.filter(ImageFilter.GaussianBlur(150))
    img.putalpha(vignette)
    out = folder / f"scene_art_{index:02d}.png"
    img.convert("RGB").save(out, quality=95)
    return out


if create:
    if mode == "استفاده از کلیپ‌های ویدئویی خودم" and not videos:
        st.error("ابتدا حداقل یک کلیپ ویدئویی انتخاب کن.")
        st.stop()
    if mode == "استفاده از کلیپ‌های ویدئویی خودم" and len(videos) != 12:
        st.error("برای خروجی ۶۰ ثانیه‌ای، دقیقاً ۱۲ کلیپ انتخاب کن؛ هر کلیپ ۵ ثانیه می‌شود.")
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
                for i, (query, label) in enumerate(SCENES):
                    status.write(f"طراحی سکانس {i + 1} از ۱۲: {label}")
                    image_path = make_scene_art(i, label, work)
                    clip_path = work / f"scene_{i:02d}.mp4"
                    vf = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"
                    subprocess.run(
                        [ffmpeg, "-y", "-loop", "1", "-framerate", "30", "-i", str(image_path),
                         "-vf", vf, "-t", "5", "-an", "-c:v", "libx264",
                         "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                         str(clip_path)],
                        check=True, capture_output=True, text=True, timeout=180,
                    )
                    scene_files.append(clip_path)
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
                command += ["-stream_loop", "-1", "-i", str(p)]
                audio_inputs.append("music")

            if narration and music:
                graph = (
                    f"[1:a]volume={narration_volume/100:.2f},apad[n];"
                    f"[2:a]volume={music_volume/100:.2f}[m];"
                    "[n][m]amix=inputs=2:duration=longest:dropout_transition=2[a]"
                )
                command += ["-filter_complex", graph, "-map", "0:v", "-map", "[a]"]
            elif narration:
                graph = f"[1:a]volume={narration_volume/100:.2f},apad[a]"
                command += ["-filter_complex", graph, "-map", "0:v", "-map", "[a]"]
            elif music:
                graph = f"[1:a]volume={music_volume/100:.2f}[a]"
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
            if mode == "ساخت خودکار ۱۲ سکانس تصویری":
                st.caption("این نسخه از گرافیک‌های اختصاصی تولیدشده در استودیو استفاده می‌کند، نه عکس‌های استوک.")

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
st.caption("ZENITH BEYOND — Beyond the Visible | Cinematic Motion Graphics v3")
