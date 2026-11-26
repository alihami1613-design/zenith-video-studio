import json
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

import imageio_ffmpeg
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont
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
    """Create a layered, premium editorial frame for the HUMAN + AI film."""
    W, H = 1080, 1920
    yy, xx = np.mgrid[0:H, 0:W]
    # Deep navy base with two soft cinematic light sources.
    g1 = np.exp(-(((xx-760)/520)**2 + ((yy-820)/760)**2)*1.6)
    g2 = np.exp(-(((xx-250)/420)**2 + ((yy-1450)/680)**2)*1.8)
    vignette = np.clip(1 - 0.42*((xx-W/2)/(W*.78))**2 - 0.38*((yy-H/2)/(H*.82))**2, .35, 1)
    arr = np.stack([
        (4 + 12*g1 + 3*g2)*vignette,
        (9 + 38*g1 + 18*g2)*vignette,
        (22 + 68*g1 + 35*g2)*vignette
    ], axis=-1).clip(0,255).astype(np.uint8)
    img = Image.fromarray(arr, "RGB")

    # Soft luminous atmosphere, composited behind the artwork.
    glow = Image.new("RGBA", (W,H), (0,0,0,0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((430,430,1180,1180), fill=(28,145,220,55))
    gd.ellipse((-250,1050,550,1850), fill=(15,210,195,35))
    glow = glow.filter(ImageFilter.GaussianBlur(115))
    img = Image.alpha_composite(img.convert("RGBA"), glow)
    d = ImageDraw.Draw(img, "RGBA")

    try:
        regular = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        f_brand = ImageFont.truetype(bold, 27)
        f_kicker = ImageFont.truetype(bold, 24)
        f_title = ImageFont.truetype(bold, 54)
        f_sub = ImageFont.truetype(regular, 22)
        f_micro = ImageFont.truetype(regular, 18)
    except Exception:
        f_brand = f_kicker = f_title = f_sub = f_micro = ImageFont.load_default()

    teal=(75,235,218,245); blue=(105,185,255,245); gold=(247,190,105,250)
    white=(240,247,255,250); muted=(150,190,215,225)
    # Fine frame, corner markers, and restrained technical grid.
    d.rounded_rectangle((38,38,W-38,H-38), radius=32, outline=(135,205,235,75), width=2)
    for x in range(100,W,120):
        d.line((x,470,x,H-120), fill=(90,155,195,13), width=1)
    d.line((88,430,W-88,430), fill=(100,205,220,75), width=2)
    d.line((88,H-175,W-88,H-175), fill=(100,205,220,55), width=2)
    for x,y,sx,sy in [(70,70,1,1),(W-70,70,-1,1),(70,H-70,1,-1),(W-70,H-70,-1,-1)]:
        d.line((x,y,x+42*sx,y), fill=teal, width=4)
        d.line((x,y,x,y+42*sy), fill=teal, width=4)

    titles = [
        "THE HUMAN MIND", "MEET THE MACHINE", "HUMAN + AI",
        "NEURAL NETWORKS", "MACHINE LEARNING", "AI IN MEDICINE",
        "INTELLIGENT INDUSTRY", "WORKING TOGETHER",
        "THE FUTURE OF WORK", "SMART CITIES",
        "A NEW CONNECTION", "OUR SHARED FUTURE"
    ]
    subtitles = [
        "A universe of thought, emotion and imagination",
        "A new kind of intelligence is taking shape",
        "Two forms of intelligence. One changing world.",
        "Patterns become knowledge through connection",
        "Systems that learn from data and experience",
        "Earlier insight. More informed decisions.",
        "Precision, automation and human expertise",
        "The strongest future is built together",
        "How will intelligent systems reshape our work?",
        "Technology woven into the fabric of daily life",
        "Trust, responsibility and the human connection",
        "The future is not predetermined. We shape it."
    ]
    # Header typography is intentionally large and readable on a phone.
    d.text((92,92), "ZENITH BEYOND", font=f_brand, fill=white)
    d.text((92,160), f"CHAPTER  {index+1:02d}   /   12", font=f_kicker, fill=gold)
    d.text((92,235), titles[index], font=f_title, fill=white, stroke_width=1, stroke_fill=(10,25,42,180))
    d.text((94,330), subtitles[index], font=f_sub, fill=muted)
    d.text((92,H-135), "HUMAN  ×  ARTIFICIAL INTELLIGENCE", font=f_kicker, fill=(190,220,235,230))
    d.text((W-220,H-135), "ZENITH  /  2026", font=f_micro, fill=gold)

    # Main-stage light rings and floating depth markers.
    d.ellipse((135,500,945,1660), outline=(70,175,220,38), width=3)
    d.ellipse((185,550,895,1610), outline=(70,175,220,24), width=2)
    for px,py in [(160,690),(910,780),(180,1450),(890,1430)]:
        d.ellipse((px-5,py-5,px+5,py+5), fill=teal)

    def human(x, y, scale=1.0):
        # Layered silhouette, facial profile, neck and shoulders.
        r=104*scale; hy=y-390*scale
        d.ellipse((x-r-16,y-390*scale-r-16,x+r+16,y-390*scale+r+16), fill=(45,125,160,38), outline=(100,205,225,85), width=3)
        d.ellipse((x-r,hy-r,x+r,hy+r), fill=(19,43,66,255), outline=(195,220,238,245), width=max(4,int(7*scale)))
        d.arc((x-66*scale,hy-78*scale,x+72*scale,hy+75*scale),195,345,fill=gold,width=max(3,int(5*scale)))
        d.ellipse((x+24*scale,hy-12*scale,x+43*scale,hy+7*scale),fill=white)
        d.line((x+62*scale,hy+18*scale,x+84*scale,hy+32*scale),fill=(180,215,235,220),width=max(2,int(4*scale)))
        d.rounded_rectangle((x-45*scale,y-275*scale,x+45*scale,y-190*scale),radius=14,fill=(20,47,70,255),outline=(165,205,225,220),width=3)
        d.rounded_rectangle((x-210*scale,y-220*scale,x+210*scale,y+245*scale),radius=int(105*scale),fill=(13,34,56,255),outline=(170,210,232,245),width=max(4,int(7*scale)))
        d.arc((x-160*scale,y-165*scale,x+160*scale,y+205*scale),195,345,fill=(80,175,205,130),width=4)
        d.ellipse((x-125*scale,y-70*scale,x-105*scale,y-50*scale),fill=teal)

    def robot(x, y, scale=1.0):
        w=235*scale; h=255*scale; hy=y-390*scale
        # Back halo and offset shadow create a dimensional, layered read.
        d.rounded_rectangle((x-w/2-18,hy-h/2-18,x+w/2+18,hy+h/2+18),radius=int(62*scale),fill=(25,115,190,38),outline=(90,175,255,95),width=4)
        d.rounded_rectangle((x-w/2,hy-h/2,x+w/2,hy+h/2),radius=int(48*scale),fill=(17,43,70,255),outline=blue,width=max(4,int(9*scale)))
        d.line((x-w*.31,hy-65*scale,x+w*.31,hy-65*scale),fill=teal,width=max(3,int(6*scale)))
        for ex in (-62,62):
            d.ellipse((x+(ex-19)*scale,hy-12*scale,x+(ex+19)*scale,hy+26*scale),fill=teal)
            d.ellipse((x+(ex-7)*scale,hy-1*scale,x+(ex+7)*scale,hy+13*scale),fill=white)
        d.arc((x-68*scale,hy+40*scale,x+68*scale,hy+112*scale),10,170,fill=gold,width=max(3,int(6*scale)))
        d.line((x,hy+h/2,x,hy+h/2+78*scale),fill=blue,width=max(6,int(15*scale)))
        d.rounded_rectangle((x-220*scale,y-215*scale,x+220*scale,y+245*scale),radius=int(95*scale),fill=(12,32,55,255),outline=blue,width=max(4,int(8*scale)))
        for j in range(3):
            d.line((x-120*scale,y-105*scale+j*75*scale,x+120*scale,y-105*scale+j*75*scale),fill=(90,185,230,155),width=max(2,int(4*scale)))
        d.ellipse((x-12*scale,y+130*scale,x+12*scale,y+154*scale),fill=gold)

    cx,cy=540,1190
    if index == 0:
        human(cx,cy,1.16)
        for r in (350,420,490):
            d.arc((cx-r,cy-650,cx+r,cy+300),195,505,fill=(gold[0],gold[1],gold[2],100 if r!=420 else 210),width=5)
        d.ellipse((cx-300,cy-610,cx+300,cy-10),outline=(100,210,235,80),width=3)
    elif index == 1:
        robot(cx,cy,1.16)
        for j in range(8):
            yy=650+j*65
            d.line((160,yy,300,yy),fill=(70,170,230,55),width=2)
            d.line((780,yy,920,yy),fill=(70,170,230,55),width=2)
    elif index == 2:
        human(340,cy,.83); robot(760,cy,.83)
        d.line((470,cy-390,610,cy-390),fill=gold,width=8)
        d.ellipse((520,cy-440,570,cy-390),fill=teal)
        d.arc((390,700,690,1450),270,90,fill=teal,width=5)
    elif index in (3,4):
        layers=[[(145,700+i*105) for i in range(7)],[(380,610+i*88) for i in range(9)],[(680,700+i*105) for i in range(7)],[(930,830+i*105) for i in range(4)]]
        for left,right in zip(layers,layers[1:]):
            for p in left:
                for q in right:
                    d.line((p,q),fill=(65,175,235,75),width=3)
        for li,layer in enumerate(layers):
            for j,(x,y) in enumerate(layer):
                r=17 if li in (0,3) else 22
                d.ellipse((x-r-7,y-r-7,x+r+7,y+r+7),fill=(40,140,205,45))
                d.ellipse((x-r,y-r,x+r,y+r),fill=gold if (j+li)%4==0 else blue,outline=white,width=2)
        d.ellipse((cx-145,cy-145,cx+145,cy+145),fill=(10,33,58,255),outline=teal,width=9)
        d.ellipse((cx-110,cy-110,cx+110,cy+110),outline=(80,220,210,100),width=3)
        d.text((cx-54,cy-42),"AI",font=ImageFont.truetype(bold,72) if os.path.exists(bold) else f_title,fill=white)
    elif index == 5:
        human(315,cy,.76)
        d.rounded_rectangle((510,650,955,1600),radius=42,fill=(9,29,52,235),outline=teal,width=6)
        d.rounded_rectangle((550,690,915,1560),radius=28,outline=(100,190,225,80),width=2)
        for r in (100,175,250):
            d.ellipse((735-r,1080-r,735+r,1080+r),outline=(80,205,225,155),width=5)
        d.line((735,780,735,1380),fill=gold,width=5); d.line((435,1080,1035,1080),fill=gold,width=5)
        d.ellipse((680,1025,790,1135),fill=(12,52,75,255),outline=teal,width=5)
        d.text((685,1045),"+",font=f_title,fill=white)
    elif index == 6:
        d.rounded_rectangle((100,1390,980,1540),radius=15,fill=(12,31,50,255),outline=blue,width=5)
        pts=[(220,1330),(370,1090),(555,1190),(735,900),(860,740)]
        d.line(pts,fill=(40,110,190,100),width=82,joint="curve")
        d.line(pts,fill=blue,width=48,joint="curve")
        for x,y in pts:
            d.ellipse((x-53,y-53,x+53,y+53),fill=(12,35,58,255),outline=gold,width=9)
            d.ellipse((x-17,y-17,x+17,y+17),fill=teal)
        for x in (180,430,680,900):
            d.rounded_rectangle((x,1470,x+75,1580),radius=8,outline=teal,width=4)
    elif index == 7:
        human(330,cy,.78); robot(760,cy,.78)
        d.line((470,cy-190,610,cy-190),fill=gold,width=12)
        d.ellipse((520,cy-240,570,cy-190),fill=teal)
        d.arc((380,700,700,1450),270,90,fill=gold,width=5)
    elif index == 8:
        human(cx,cy,.9)
        for j in range(4):
            y=650+j*185
            d.rounded_rectangle((95,y,355,y+120),radius=22,fill=(13,37,62,240),outline=gold if j%2==0 else teal,width=5)
            d.ellipse((125,y+38,165,y+78),fill=teal)
            d.line((190,y+48,315,y+48),fill=white,width=5)
            d.line((190,y+75,285,y+75),fill=muted,width=3)
    elif index == 9:
        for j in range(7):
            x=80+j*135; bh=310+(j*117)%480
            d.rounded_rectangle((x,1500-bh,x+100,1500),radius=10,fill=(13,39,65,255),outline=blue,width=5)
            for wy in range(1520-bh,1450,65):
                d.rounded_rectangle((x+20,wy,x+37,wy+24),radius=4,fill=gold)
                d.rounded_rectangle((x+59,wy,x+76,wy+24),radius=4,fill=teal)
        d.arc((80,560,1000,1700),190,350,fill=gold,width=7)
        for j in range(6):
            d.ellipse((160+j*145,800+(j%2)*95,174+j*145,814+(j%2)*95),fill=teal)
    elif index == 10:
        human(330,cy,.82); robot(760,cy,.82)
        d.line((470,cy-415,610,cy-415),fill=gold,width=8)
        for j in range(7):
            x=480+j*20
            d.ellipse((x,cy-438,x+14,cy-424),fill=teal)
        d.arc((300,650,780,1540),205,335,fill=gold,width=6)
    else:
        human(330,cy,.82); robot(760,cy,.82)
        d.arc((100,540,980,1710),195,525,fill=gold,width=9)
        d.ellipse((cx-34,cy-45,cx+34,cy+23),fill=teal)
        for j in range(12):
            ang=j*math.pi/6
            px=cx+int(300*math.cos(ang)); py=cy+int(470*math.sin(ang))
            d.ellipse((px-5,py-5,px+5,py+5),fill=(gold[0],gold[1],gold[2],180))

    out=folder / f"scene_art_{index:02d}.png"
    img.convert("RGB").save(out, quality=96)
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
                    vf = "zoompan=z='min(1+0.00045*on,1.07)':x='iw/2-(iw/zoom/2)+sin(on/38)*12':y='ih/2-(ih/zoom/2)+cos(on/51)*10':d=1:s=1080x1920:fps=30,format=yuv420p"
                    subprocess.run(
                        [ffmpeg, "-y", "-loop", "1", "-framerate", "30", "-i", str(image_path),
                         "-vf", vf, "-t", "5.25", "-an", "-c:v", "libx264",
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
                         "-t", "5.25", "-vf",
                         "scale=1080:1920:force_original_aspect_ratio=increase,"
                         "crop=1080:1920,setsar=1,fps=30,format=yuv420p",
                         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                         str(clip_path)],
                        check=True, capture_output=True, text=True, timeout=240,
                    )
                    scene_files.append(clip_path)
                    progress.progress(int((i + 1) / len(videos) * 65))

            # Join the twelve chapters with short cinematic dissolves.
            silent_video = work / "silent.mp4"
            inputs = []
            graph_parts = []
            for i, clip in enumerate(scene_files):
                inputs += ["-i", str(clip)]
                graph_parts.append(f"[{i}:v]settb=AVTB,setpts=PTS-STARTPTS,fps=30,format=yuv420p[v{i}]")
            last = "v0"
            for i in range(1, len(scene_files)):
                out = f"xf{i}"
                offset = i * 5.0
                graph_parts.append(f"[{last}][v{i}]xfade=transition=fade:duration=0.25:offset={offset:.2f}[{out}]")
                last = out
            subprocess.run(
                [ffmpeg, "-y", *inputs, "-filter_complex", ";".join(graph_parts),
                 "-map", f"[{last}]", "-an", "-t", "60", "-c:v", "libx264",
                 "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
                 str(silent_video)],
                check=True, capture_output=True, text=True, timeout=600,
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
                "-t", "60", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
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
                st.caption("نسخه ارتقایافته: طراحی چندلایه، حرکت دوربین آرام، ترنزیشن سینمایی و تایپوگرافی خواناتر. این موتور موشن‌گرافیک است، نه فوتورئالیسم سه‌بعدی.")

    except subprocess.TimeoutExpired:
        st.error("رندر بیش از زمان مجاز طول کشید. تعداد یا حجم کلیپ‌ها را کمتر کن.")
    except subprocess.CalledProcessError as e:
        st.error("پردازش ویدئو ناموفق بود.")
        if e.stderr:
            st.code(e.stderr[-3500:])
    except Exception as e:
        st.error(f"خطای غیرمنتظره: {e}")

st.markdown("---")
st.caption("ZENITH BEYOND — Human & AI | Cinematic Motion Graphics v5")
