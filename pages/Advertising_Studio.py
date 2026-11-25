import re
import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg
import streamlit as st

st.set_page_config(page_title="Advertising Studio", page_icon="🎬", layout="wide")
st.markdown("""
<style>
html, body, [class*="css"] { direction: rtl; text-align: right; }
.block-container { max-width: 1150px; padding-top: 1.5rem; }
</style>
""", unsafe_allow_html=True)

st.title("🎬 ADVERTISING STUDIO")
st.caption("استودیوی ساخت تیزر تبلیغاتی | Luxury • Cinematic • High Energy")
st.info("این بخش مستقل است؛ فایل‌ها و پروژه‌های LUNAVERA و ZENITH را تغییر نمی‌دهد.")

st.markdown("### ۱. ویدئوهای تبلیغاتی")
videos = st.file_uploader(
    "کلیپ‌ها را به ترتیب دلخواه انتخاب کن",
    type=["mp4", "mov", "mkv", "avi", "webm"],
    accept_multiple_files=True,
    key="ad_video_assets",
)
st.caption("حداکثر ۱۲ کلیپ؛ هر فایل تا سقف ۲۰۰ مگابایت. از فوتیج‌هایی استفاده کن که مجوز استفاده تجاری‌شان را داری.")

st.markdown("### ۲. تصاویر تبلیغاتی")
photos = st.file_uploader(
    "عکس‌های محصول یا محیط را انتخاب کن",
    type=["jpg", "jpeg", "png", "webp"],
    accept_multiple_files=True,
    key="ad_photo_assets",
)
st.caption("می‌توانی عکس مبل را هم کنار ویدئوها اضافه کنی؛ تصاویر به صحنه‌های کوتاه با حرکت آرام دوربین تبدیل می‌شوند. مجموع عکس‌ها و کلیپ‌ها حداکثر ۱۲ فایل باشد.")

c1, c2 = st.columns(2)
with c1:
    music = st.file_uploader("موسیقی تبلیغاتی (اختیاری)", type=["mp3", "wav", "m4a", "aac", "ogg"], key="ad_music")
with c2:
    narration = st.file_uploader("گویندگی (اختیاری)", type=["mp3", "wav", "m4a", "aac", "ogg"], key="ad_voice")

st.markdown("### ۳. تنظیمات تدوین")
a, b, c = st.columns(3)
with a:
    duration = st.selectbox("مدت خروجی", [30, 45, 50, 60], index=2, format_func=lambda x: f"{x} ثانیه")
with b:
    style = st.selectbox("حال‌وهوای رنگ", ["لوکس مشکی و طلایی", "سینمایی طبیعی", "پرکنتراست و پرانرژی"])
with c:
    quality = st.selectbox("کیفیت خروجی", ["1080p متعادل", "1080p با حجم کمتر"], index=0)

music_level = st.slider("بلندی موسیقی", 0, 100, 28)
voice_level = st.slider("بلندی گویندگی", 0, 150, 100)

st.caption("خروجی: MP4 / H.264 / Full HD 1920×1080 / 24fps. شامل یکسان‌سازی قاب و فریم‌ریت، اصلاح رنگ، محو ورود و خروج و میکس صداست.")

def run_ffmpeg(cmd, timeout=900):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        detail = (p.stderr or p.stdout or "خطای نامشخص FFmpeg")[-3500:]
        raise RuntimeError(detail)

def media_duration(ffmpeg, path):
    p = subprocess.run([ffmpeg, "-i", str(path), "-f", "null", "-"],
                       capture_output=True, text=True, timeout=90)
    match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", p.stderr)
    if not match:
        raise ValueError(f"مدت فایل «{path.name}» قابل تشخیص نیست یا فایل ویدئویی معتبر نیست.")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)

if st.button("✨ ساخت تیزر تبلیغاتی", type="primary", use_container_width=True):
    assets_count = len(videos or []) + len(photos or [])
    if assets_count == 0:
        st.error("ابتدا حداقل یک کلیپ ویدئویی یا یک عکس انتخاب کن.")
        st.stop()
    if assets_count > 12:
        st.error("برای پایداری رندر، مجموع عکس‌ها و کلیپ‌ها حداکثر ۱۲ فایل باشد.")
        st.stop()

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    progress = st.progress(0)
    status = st.empty()
    try:
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            normalized = []
            assets = [(item, "video") for item in (videos or [])] + [(item, "photo") for item in (photos or [])]
            per_clip = duration / len(assets)

            for i, (uploaded, asset_type) in enumerate(assets):
                kind_label = "عکس" if asset_type == "photo" else "کلیپ"
                status.write(f"بررسی و آماده‌سازی {kind_label} {i+1} از {len(assets)} ...")
                suffix = Path(uploaded.name).suffix.lower() or (".jpg" if asset_type == "photo" else ".mp4")
                src = work / f"input_{i}{suffix}"
                dst = work / f"clip_{i:02d}.mp4"
                src.write_bytes(uploaded.getbuffer())

                vf = "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1,fps=24,eq=contrast=1.06:saturation=1.10:brightness=0.005,format=yuv420p"
                if style == "لوکس مشکی و طلایی":
                    vf += ",curves=all='0/0 0.20/0.15 0.75/0.82 1/1'"
                elif style == "پرکنتراست و پرانرژی":
                    vf += ",eq=contrast=1.12:saturation=1.18"

                if asset_type == "video":
                    source_duration = media_duration(ffmpeg, src)
                    if source_duration + 0.15 < per_clip:
                        raise ValueError(
                            f"مدت کلیپ «{uploaded.name}» فقط {source_duration:.1f} ثانیه است؛ "
                            f"برای زمان‌بندی فعلی حداقل {per_clip:.1f} ثانیه لازم است. "
                            "کلیپ طولانی‌تری انتخاب کن یا تعداد فایل‌ها را کمتر کن."
                        )
                    vf += f",trim=duration={per_clip:.3f},setpts=PTS-STARTPTS"
                    input_args = ["-i", str(src)]
                else:
                    frames = max(1, round(per_clip * 24))
                    vf += f",zoompan=z='min(zoom+0.0005,1.08)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080:fps=24,trim=duration={per_clip:.3f},setpts=PTS-STARTPTS"
                    input_args = ["-loop", "1", "-framerate", "24", "-i", str(src), "-t", f"{per_clip:.3f}"]

                run_ffmpeg([
                    ffmpeg, "-y", *input_args, "-vf", vf,
                    "-an", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "23" if quality == "1080p متعادل" else "26",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)
                ])
                normalized.append(dst)
                progress.progress(int((i + 1) / (len(assets) + 2) * 65))

            status.write("اتصال سکانس‌ها و آماده‌سازی صدا ...")
            concat = work / "concat.txt"
            with concat.open("w", encoding="utf-8", newline="\n") as f:
                for p in normalized:
                    safe_path = p.as_posix().replace("'", "'\\''")
                    f.write(f"file '{safe_path}'\n")

            joined = work / "joined.mp4"
            run_ffmpeg([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
                        "-c", "copy", str(joined)])
            progress.progress(72)

            final = work / "ADVERTISING_SHOWREEL.mp4"
            cmd = [ffmpeg, "-y", "-i", str(joined)]
            if narration:
                vp = work / ("voice" + (Path(narration.name).suffix or ".mp3"))
                vp.write_bytes(narration.getbuffer())
                cmd += ["-i", str(vp)]
            if music:
                mp = work / ("music" + (Path(music.name).suffix or ".mp3"))
                mp.write_bytes(music.getbuffer())
                cmd += ["-stream_loop", "-1", "-i", str(mp)]

            video_fade = f"fade=t=in:st=0:d=0.7,fade=t=out:st={max(0, duration-0.8):.3f}:d=0.8"
            cmd += ["-vf", video_fade, "-map", "0:v:0"]

            audio_fade = f"afade=t=in:st=0:d=0.35,afade=t=out:st={max(0, duration-0.8):.3f}:d=0.8"
            if narration and music:
                graph = (
                    f"[1:a]volume={voice_level/100:.2f}[v];"
                    f"[2:a]volume={music_level/100:.2f}[m];"
                    f"[v][m]amix=inputs=2:duration=longest:dropout_transition=2,"
                    f"atrim=duration={duration},{audio_fade}[a]"
                )
                cmd += ["-filter_complex", graph, "-map", "[a]"]
            elif narration:
                cmd += ["-map", "1:a:0", "-af",
                        f"volume={voice_level/100:.2f},{audio_fade}"]
            elif music:
                cmd += ["-map", "2:a:0", "-af",
                        f"volume={music_level/100:.2f},{audio_fade}"]
            else:
                cmd += ["-an"]

            cmd += ["-t", str(duration), "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "23" if quality == "1080p متعادل" else "26",
                    "-pix_fmt", "yuv420p"]
            if narration or music:
                cmd += ["-c:a", "aac", "-b:a", "160k"]
            cmd += ["-movflags", "+faststart", str(final)]

            status.write("رندر نهایی تیزر در حال انجام است ...")
            run_ffmpeg(cmd, timeout=1200)
            data = final.read_bytes()
            progress.progress(100)
            status.success(f"تیزر آماده شد. حجم فایل: {len(data)/(1024*1024):.1f} مگابایت")
            st.video(data)
            st.download_button("⬇️ دریافت تیزر تبلیغاتی", data=data,
                               file_name="ADVERTISING_SHOWREEL.mp4", mime="video/mp4",
                               use_container_width=True)
    except subprocess.TimeoutExpired:
        st.error("زمان رندر تمام شد. تعداد یا مدت کلیپ‌ها را کمتر کن.")
    except Exception as e:
        st.error("ساخت تیزر کامل نشد.")
        st.code(str(e)[-3500:])

st.divider()
st.caption("نکته: عکس‌ها به صحنه‌های ویدئویی کوتاه با حرکت آرام زوم تبدیل می‌شوند. این نسخه تدوین خودکار عکس‌ها و کلیپ‌های بارگذاری‌شده را انجام می‌دهد؛ جست‌وجو و دریافت خودکار فوتیج استوک و موشن‌گرافیک اختصاصی هنوز به آن متصل نشده است.")
