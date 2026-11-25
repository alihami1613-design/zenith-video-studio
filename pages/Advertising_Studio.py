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
st.caption("برای نمونه‌کار لوکس، کلیپ‌های محصول، خودرو، شهر شبانه، فناوری یا جزئیات نزدیک مناسب‌اند. از فایل‌هایی استفاده کن که مجوز استفاده تجاری‌شان را داری.")

c1, c2 = st.columns(2)
with c1:
    music = st.file_uploader("موسیقی تبلیغاتی (اختیاری)", type=["mp3", "wav", "m4a", "aac", "ogg"], key="ad_music")
with c2:
    narration = st.file_uploader("گویندگی (اختیاری)", type=["mp3", "wav", "m4a", "aac", "ogg"], key="ad_voice")

st.markdown("### ۲. تنظیمات تدوین")
a, b, c = st.columns(3)
with a:
    duration = st.selectbox("مدت خروجی", [30, 45, 50, 60], index=2, format_func=lambda x: f"{x} ثانیه")
with b:
    style = st.selectbox("حال‌وهوای رنگ", ["لوکس مشکی و طلایی", "سینمایی طبیعی", "پرکنتراست و پرانرژی"])
with c:
    quality = st.selectbox("کیفیت خروجی", ["1080p متعادل", "1080p با حجم کمتر"], index=0)

music_level = st.slider("بلندی موسیقی", 0, 100, 28)
voice_level = st.slider("بلندی گویندگی", 0, 150, 100)

st.caption("خروجی: MP4 / H.264 / Full HD 1920×1080 / 24fps. تدوین خودکار شامل یکسان‌سازی قاب و فریم‌ریت، اصلاح رنگ، محو ورود و خروج و میکس صداست.")

def run_ffmpeg(cmd, timeout=900):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        detail = (p.stderr or p.stdout or "خطای نامشخص FFmpeg")[-3500:]
        raise RuntimeError(detail)

if st.button("✨ ساخت تیزر تبلیغاتی", type="primary", use_container_width=True):
    if not videos:
        st.error("ابتدا حداقل یک کلیپ ویدئویی انتخاب کن.")
        st.stop()
    if len(videos) > 12:
        st.error("برای پایداری رندر، حداکثر ۱۲ کلیپ انتخاب کن.")
        st.stop()

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    progress = st.progress(0)
    status = st.empty()
    try:
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            normalized = []
            per_clip = max(2.0, duration / len(videos))
            for i, uploaded in enumerate(videos):
                status.write(f"آماده‌سازی کلیپ {i+1} از {len(videos)} ...")
                suffix = Path(uploaded.name).suffix or ".mp4"
                src = work / f"input_{i}{suffix}"
                dst = work / f"clip_{i:02d}.mp4"
                src.write_bytes(uploaded.getbuffer())
                vf = "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1,fps=24,eq=contrast=1.08:saturation=1.12:brightness=0.01,format=yuv420p"
                if style == "لوکس مشکی و طلایی":
                    vf += ",curves=all='0/0 0.20/0.15 0.75/0.82 1/1'"
                elif style == "پرکنتراست و پرانرژی":
                    vf += ",eq=contrast=1.16:saturation=1.20"
                vf += f",trim=duration={per_clip:.3f},setpts=PTS-STARTPTS"
                run_ffmpeg([
                    ffmpeg, "-y", "-i", str(src), "-vf", vf,
                    "-an", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "23" if quality == "1080p متعادل" else "26",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)
                ])
                normalized.append(dst)
                progress.progress(int((i + 1) / (len(videos) + 2) * 70))

            status.write("اتصال سکانس‌ها و آماده‌سازی صدا ...")
            concat = work / "concat.txt"
            with concat.open("w", encoding="utf-8") as f:
                for p in normalized:
                    f.write("file '" + p.as_posix().replace("'", "'\\''") + "'\\n")
            joined = work / "joined.mp4"
            run_ffmpeg([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
                        "-c", "copy", str(joined)])

            final = work / "ADVERTISING_SHOWREEL.mp4"
            cmd = [ffmpeg, "-y", "-i", str(joined)]
            audio_inputs = []
            if narration:
                vp = work / ("voice" + (Path(narration.name).suffix or ".mp3"))
                vp.write_bytes(narration.getbuffer())
                cmd += ["-i", str(vp)]
                audio_inputs.append("voice")
            if music:
                mp = work / ("music" + (Path(music.name).suffix or ".mp3"))
                mp.write_bytes(music.getbuffer())
                cmd += ["-stream_loop", "-1", "-i", str(mp)]
                audio_inputs.append("music")

            if narration and music:
                graph = f"[1:a]volume={voice_level/100:.2f}[v];[2:a]volume={music_level/100:.2f}[m];[v][m]amix=inputs=2:duration=longest:dropout_transition=2,atrim=duration={duration}[a]"
                cmd += ["-filter_complex", graph, "-map", "0:v", "-map", "[a]"]
            elif narration:
                cmd += ["-map", "0:v", "-map", "1:a", "-af", f"volume={voice_level/100:.2f},atrim=duration={duration}"]
            elif music:
                cmd += ["-map", "0:v", "-map", "1:a", "-af", f"volume={music_level/100:.2f},atrim=duration={duration}"]
            else:
                cmd += ["-map", "0:v", "-an"]

            cmd += ["-t", str(duration), "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "23" if quality == "1080p متعادل" else "26",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", str(final)]
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
st.caption("نکته: این نسخه تدوین خودکار کلیپ‌های بارگذاری‌شده را انجام می‌دهد؛ جست‌وجو و دریافت خودکار فوتیج استوک و موشن‌گرافیک اختصاصی هنوز به آن متصل نشده است.")
