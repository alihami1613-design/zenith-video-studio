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
    st.success("۱۲ سکانس × ۵ ثانیه = ۶۰ ثانیه | عمودی 9:16 | طراحی بصری اختصاصی انسان و هوش مصنوعی")
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
st.write("MP4 • عمودی 9:16 • Full HD 1080×1920 • 30 FPS • H.264")
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
    """Create a vertical, coherent cinematic illustration with recognizable human/AI subjects."""
    W, H = 1080, 1920
    yy, xx = np.mgrid[0:H, 0:W]
    glow = np.clip(1 - np.sqrt(((xx - 700) / 760) ** 2 + ((yy - 980) / 1150) ** 2), 0, 1)
    t = yy / H
    arr = np.stack([
        3 + 8 * glow,
        8 + 30 * glow + 3 * t,
        20 + 48 * glow + 7 * t,
    ], axis=-1).clip(0,255).astype(np.uint8)
    img = Image.fromarray(arr, "RGB")
    d = ImageDraw.Draw(img, "RGBA")
    # Vertical cinematic frame, restrained HUD lines and atmospheric light.
    d.rounded_rectangle((42, 42, W-42, H-42), radius=30, outline=(130,205,225,75), width=2)
    for x in range(90, W, 90):
        d.line((x, 0, x, H), fill=(100,175,210,12), width=1)
    teal=(65,225,215,235); blue=(95,175,255,235); gold=(245,190,105,245)
    white=(235,244,250,245)
    cx, cy = 540, 1110

    def human(x, y, scale=1.0, color=(175,205,225,255), side=False):
        # Recognizable human bust: head, neck, shoulders and facial profile.
        r=int(105*scale)
        d.ellipse((x-r,y-430*scale-r,x+r,y-430*scale+r), fill=(18,38,60,255), outline=color, width=max(3,int(8*scale)))
        d.ellipse((x-r*.65,y-430*scale-r*.65,x+r*.65,y-430*scale+r*.65), outline=(gold if side else (120,190,220,150)), width=max(2,int(3*scale)))
        d.rounded_rectangle((x-48*scale,y-330*scale,x+48*scale,y-245*scale), radius=18, fill=(18,38,60,255), outline=color, width=4)
        d.rounded_rectangle((x-210*scale,y-270*scale,x+210*scale,y+210*scale), radius=int(100*scale), fill=(15,35,58,255), outline=color, width=max(3,int(7*scale)))
        d.arc((x-78*scale,y-485*scale,x+95*scale,y-360*scale), 185, 345, fill=gold, width=max(2,int(5*scale)))
        d.ellipse((x+25*scale,y-440*scale,x+43*scale,y-422*scale), fill=gold)

    def robot(x, y, scale=1.0):
        # Clearly mechanical head, luminous eyes, segmented neck and shoulders.
        w,h=230*scale,255*scale
        d.rounded_rectangle((x-w/2,y-430*scale-h/2,x+w/2,y-430*scale+h/2), radius=int(48*scale), fill=(18,43,68,255), outline=blue, width=max(4,int(9*scale)))
        d.line((x-w*.34,y-430*scale-65*scale,x+w*.34,y-430*scale-65*scale), fill=teal, width=max(3,int(6*scale)))
        for ex in (-62,62):
            d.ellipse((x+(ex-17)*scale,y-430*scale-15*scale,x+(ex+17)*scale,y-430*scale+19*scale), fill=teal)
        d.arc((x-65*scale,y-430*scale+45*scale,x+65*scale,y-430*scale+110*scale), 10, 170, fill=gold, width=max(3,int(6*scale)))
        d.line((x,y-300*scale,x,y-235*scale), fill=blue, width=max(6,int(16*scale)))
        d.rounded_rectangle((x-220*scale,y-250*scale,x+220*scale,y+210*scale), radius=int(95*scale), fill=(13,31,52,255), outline=blue, width=max(4,int(8*scale)))
        for j in range(3):
            d.line((x-120*scale,y-140*scale+j*80*scale,x+120*scale,y-140*scale+j*80*scale), fill=(90,185,230,150), width=max(2,int(4*scale)))

    titles = [
        "THE HUMAN MIND", "MEET THE MACHINE", "HUMAN + AI",
        "NEURAL NETWORKS", "MACHINE LEARNING", "AI IN MEDICINE",
        "INTELLIGENT INDUSTRY", "WORKING TOGETHER",
        "THE FUTURE OF WORK", "SMART CITIES",
        "A NEW CONNECTION", "OUR SHARED FUTURE"
    ]
    # A distinct visual story beat for each chapter.
    if index == 0:
        human(cx,cy,1.15)
        d.arc((cx-360,cy-760,cx+360,cy-60), 200, 520, fill=gold, width=8)
    elif index == 1:
        robot(cx,cy,1.18)
    elif index == 2:
        human(350,cy,0.82); robot(760,cy,0.82)
        d.line((475,cy-400,635,cy-400), fill=gold, width=7)
        d.ellipse((525,cy-450,575,cy-400), fill=teal)
    elif index in (3,4):
        # Neural network surrounding a central glowing AI core.
        layers=[[(150,650+i*105) for i in range(7)],
                [(390,590+i*85) for i in range(9)],
                [(680,650+i*105) for i in range(7)],
                [(920,800+i*105) for i in range(4)]]
        for left,right in zip(layers,layers[1:]):
            for p in left:
                for q in right:
                    d.line((p,q), fill=(65,175,235,90), width=3)
        for li,layer in enumerate(layers):
            for j,(x,y) in enumerate(layer):
                r=16 if li in (0,3) else 20
                d.ellipse((x-r,y-r,x+r,y+r), fill=gold if (j+li)%4==0 else blue, outline=white, width=2)
        d.ellipse((cx-115,cy-115,cx+115,cy+115), fill=(12,36,60,255), outline=teal, width=9)
        d.text((cx-48,cy-20),"AI",fill=white)
    elif index == 5:
        human(330,cy,0.72)
        # Medical scan panel and diagnostic cross.
        d.rounded_rectangle((520,650,950,1510), radius=35, fill=(10,30,52,220), outline=teal, width=6)
        for r in (95,165,235):
            d.ellipse((735-r,1050-r,735+r,1050+r), outline=(80,205,225,170), width=5)
        d.line((735,780,735,1320), fill=gold, width=5)
        d.line((465,1050,1005,1050), fill=gold, width=5)
    elif index == 6:
        # Industrial robotic arm, conveyor and factory silhouette.
        d.rectangle((100,1350,980,1500), fill=(12,30,48,255), outline=blue, width=5)
        pts=[(250,1300),(390,1080),(560,1170),(740,900),(850,760)]
        d.line(pts, fill=blue, width=52, joint="curve")
        for x,y in pts:
            d.ellipse((x-48,y-48,x+48,y+48), fill=(12,35,58,255), outline=gold, width=9)
        for x in (180,430,680,900):
            d.rectangle((x,1470,x+75,1570), outline=teal, width=4)
    elif index == 7:
        human(330,cy,0.78); robot(760,cy,0.78)
        d.line((470,cy-180,610,cy-180), fill=gold, width=12)
        d.ellipse((520,cy-225,570,cy-175), fill=teal)
    elif index == 8:
        human(cx,cy,0.9)
        for j in range(4):
            y=650+j*170
            d.rounded_rectangle((90,y,310,y+105), radius=18, fill=(12,36,60,230), outline=gold if j%2==0 else teal, width=5)
            d.line((130,y+55,265,y+55), fill=white, width=4)
    elif index == 9:
        for j in range(7):
            x=90+j*130; h=300+(j*113)%440
            d.rectangle((x,1450-h,x+92,1450), fill=(13,39,64,255), outline=blue, width=5)
            for wy in range(1480-h,1420,65):
                d.rectangle((x+22,wy,x+38,wy+22), fill=gold)
                d.rectangle((x+55,wy,x+71,wy+22), fill=teal)
        d.arc((100,600,980,1650),190,350,fill=gold,width=6)
    elif index == 10:
        human(330,cy,0.82); robot(760,cy,0.82)
        d.line((460,cy-425,620,cy-425), fill=gold, width=8)
        for j in range(7):
            x=480+j*20
            d.ellipse((x,cy-445,x+14,cy-431),fill=teal)
    else:
        human(330,cy,0.82); robot(760,cy,0.82)
        d.arc((120,520,960,1640),200,520,fill=gold,width=8)
        d.ellipse((cx-24,cy-30,cx+24,cy+18),fill=teal)

    # Clear editorial hierarchy; title text is kept away from the main subject.
    d.text((95,115),"ZENITH BEYOND",fill=(205,225,238,230))
    d.text((95,205),f"{index+1:02d} / 12",fill=gold)
    d.text((95,285),titles[index],fill=white)
    d.line((95,350,500,350),fill=teal,width=4)
    d.text((95,390),"HUMAN  ×  ARTIFICIAL INTELLIGENCE",fill=(155,195,215,225))
    out=folder / f"scene_art_{index:02d}.png"
    img.save(out, quality=95)
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
                    vf = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"
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

            final_video = work / "ZENITH_HUMAN_AND_AI_VERTICAL_60S.mp4"
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
                file_name="ZENITH_HUMAN_AND_AI_VERTICAL_60S.mp4",
                mime="video/mp4",
                use_container_width=True,
            )
            if mode == "ساخت خودکار ۱۲ سکانس تصویری":
                st.caption("این نسخه از گرافیک‌های اختصاصی انسان و AI استفاده می‌کند؛ برای فوتورئالیسم سه‌بعدی و حرکت واقعی، موتور تولید ویدئوی AI جداگانه لازم است.")

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
st.caption("ZENITH BEYOND — Vertical Human & AI | Motion Graphics v4")
