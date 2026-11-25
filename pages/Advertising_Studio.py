import re
import html
import requests
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
    music = st.file_uploader("موسیقی تبلیغاتی (اختیاری؛ موسیقی پیش‌فرض موجود است)", type=["mp3", "wav", "m4a", "aac", "ogg"], key="ad_music")
with c2:
    narration = st.file_uploader("گویندگی (اختیاری)", type=["mp3", "wav", "m4a", "aac", "ogg"], key="ad_voice")

st.markdown("### ۳. تنظیمات تدوین")
a, b, c, d = st.columns(4)
with a:
    duration = st.selectbox("مدت خروجی", [15, 30, 45, 60], index=0, format_func=lambda x: f"{x} ثانیه")
with b:
    orientation = st.selectbox("قالب تصویر", ["عمودی 9:16 — اینستاگرام Reels", "افقی 16:9"], index=0)
with c:
    style = st.selectbox("حال‌وهوای رنگ", ["لوکس مشکی و طلایی", "سینمایی طبیعی", "پرکنتراست و پرانرژی"])
with d:
    quality = st.selectbox("کیفیت خروجی", ["1080p متعادل", "1080p با حجم کمتر"], index=0)

st.markdown("#### ۴. کارگردانی و جلوه‌های تصویری")
e1, e2, e3 = st.columns(3)
with e1:
    edit_preset = st.selectbox(
        "سبک تدوین",
        ["LUXURY — لوکس و شیک", "CINEMATIC — سینمایی", "DYNAMIC — پرانرژی"],
        index=0,
    )
with e2:
    transition = st.selectbox(
        "اتصال صحنه‌ها",
        ["برش حرفه‌ای", "محو شدن از سیاهی"],
        index=0,
    )
with e3:
    vfx_strength = st.slider("شدت جلوه تصویری", 0, 100, 45)

st.markdown("#### ۵. موشن‌گرافیک متحرک")
motion_graphics = st.checkbox("افزودن موشن‌گرافیک تبلیغاتی", value=True)
mg_title = st.text_input("تیتر اصلی موشن‌گرافیک", value="DISCOVER THE DIFFERENCE", max_chars=48)
mg_subtitle = st.text_input("زیرتیتر", value="DESIGNED FOR YOUR LIFESTYLE", max_chars=64)
mg_cta = st.text_input("متن دعوت به اقدام", value="LEARN MORE", max_chars=24)
mg_style = st.selectbox("جایگاه و سبک نمایش", ["لوکس — پایین تصویر", "مدرن — مرکز تصویر", "مینیمال — گوشه پایین"], index=0)


with st.expander("🎛️ کنترل‌های تکمیلی افکت حرفه‌ای", expanded=False):
    fx_mode = st.selectbox("افکت ویژه", ["بدون افکت اضافه", "Glow نرم", "فیلم قدیمی (Film)", "سیاه‌وسفید", "RGB Split ساده (Glitch رنگی)"], index=0)
    glow_amount = st.slider("شدت Glow", 0, 100, 30, disabled=(fx_mode != "Glow نرم"))
    grain_amount = st.slider("میزان Grain", 0, 100, 15, disabled=(fx_mode != "فیلم قدیمی (Film)"))
    use_flash = st.checkbox("افکت Flash کوتاه (روشنایی)", value=False)

if orientation.startswith("عمودی"):
    output_w, output_h = 1080, 1920
else:
    output_w, output_h = 1920, 1080

music_level = st.slider("بلندی موسیقی", 0, 100, 28)
voice_level = st.slider("بلندی گویندگی", 0, 150, 100)
if music:
    st.audio(music)
else:
    st.caption("اگر موسیقی بارگذاری نکنی، برنامه موسیقی تبلیغاتی پیش‌فرض را از Wikimedia Commons دریافت می‌کند.")
if narration:
    st.audio(narration)

st.caption("خروجی: MP4 / H.264 / 1080p / 24fps. قالب عمودی 9:16 برای نمایش تمام‌صفحه Reels یا افقی 16:9.")
st.caption("موسیقی پیش‌فرض: Soft Corporate — MusicLFiles | مجوز CC BY 4.0؛ در انتشار ویدئو نام سازنده و پیوند منبع را ذکر کن: https://commons.wikimedia.org/wiki/File:Soft_Corporate_by_MusicLFiles.ogg")

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
            music_path = work / "default_or_uploaded_music.ogg"
            music_ready = False
            if music:
                music_path = work / ("uploaded_music" + (Path(music.name).suffix or ".mp3"))
                music_path.write_bytes(music.getbuffer())
                music_ready = True
            else:
                status.write("تلاش برای دریافت موسیقی پیش‌فرض ...")
                # If the public host rate-limits downloads (HTTP 429), continue rendering
                # instead of failing the entire advertisement.
                audio_url = "https://upload.wikimedia.org/wikipedia/commons/5/5f/Soft_Corporate_by_MusicLFiles.ogg"
                try:
                    audio_response = requests.get(
                        audio_url,
                        headers={"User-Agent": "ZENITH-Advertising-Studio/1.0 (video editor)"},
                        timeout=45,
                    )
                    audio_response.raise_for_status()
                    content_type = audio_response.headers.get("Content-Type", "").lower()
                    if len(audio_response.content) < 100000 or not (content_type.startswith("audio/") or "application/ogg" in content_type):
                        raise RuntimeError("فایل موسیقی پیش‌فرض معتبر دریافت نشد.")
                    music_path.write_bytes(audio_response.content)
                    music_ready = True
                except (requests.RequestException, RuntimeError) as audio_error:
                    st.warning("موسیقی پیش‌فرض در دسترس نیست (احتمالاً محدودیت موقت سرور). رندر ادامه پیدا می‌کند؛ برای داشتن صدا، فایل موسیقی خودت را بارگذاری کن. جزئیات: " + str(audio_error)[:240])
            assets = [(item, "video") for item in (videos or [])] + [(item, "photo") for item in (photos or [])]
            per_clip = duration / len(assets)

            for i, (uploaded, asset_type) in enumerate(assets):
                kind_label = "عکس" if asset_type == "photo" else "کلیپ"
                status.write(f"بررسی و آماده‌سازی {kind_label} {i+1} از {len(assets)} ...")
                suffix = Path(uploaded.name).suffix.lower() or (".jpg" if asset_type == "photo" else ".mp4")
                src = work / f"input_{i}{suffix}"
                dst = work / f"clip_{i:02d}.mp4"
                src.write_bytes(uploaded.getbuffer())

                vf = f"scale={output_w}:{output_h}:force_original_aspect_ratio=increase,crop={output_w}:{output_h},setsar=1,fps=24,eq=contrast=1.06:saturation=1.10:brightness=0.005"
                strength = vfx_strength / 100.0
                if style == "لوکس مشکی و طلایی":
                    vf += ",curves=all='0/0 0.20/0.15 0.75/0.82 1/1'"
                elif style == "پرکنتراست و پرانرژی":
                    vf += ",eq=contrast=1.12:saturation=1.18"

                # Practical FFmpeg finishing effects: vignette, sharpening and restrained grade.
                if edit_preset.startswith("LUXURY"):
                    vf += f",vignette=PI/{5.0 - 1.2 * strength},eq=contrast={1.04 + 0.10 * strength:.3f}:saturation={1.02 + 0.12 * strength:.3f}"
                    if vfx_strength >= 20:
                        vf += f",unsharp=5:5:{0.25 + 0.45 * strength:.2f}:5:5:0"
                elif edit_preset.startswith("CINEMATIC"):
                    vf += f",vignette=PI/{4.5 - 1.0 * strength},eq=contrast={1.06 + 0.12 * strength:.3f}:saturation={0.94 + 0.08 * strength:.3f},unsharp=5:5:{0.20 + 0.35 * strength:.2f}:5:5:0"
                else:
                    vf += f",eq=contrast={1.10 + 0.16 * strength:.3f}:saturation={1.12 + 0.20 * strength:.3f},unsharp=5:5:{0.35 + 0.55 * strength:.2f}:5:5:0"


                # Extra selectable finishing effects implemented with FFmpeg filters.
                if fx_mode == "Glow نرم":
                    vf += f",gblur=sigma={1.0 + glow_amount/35:.2f},eq=brightness={glow_amount/500:.3f}"
                elif fx_mode == "فیلم قدیمی (Film)":
                    vf += f",noise=alls={grain_amount}:allf=t,eq=saturation=0.92"
                elif fx_mode == "سیاه‌وسفاد":
                    vf += ",hue=s=0,eq=contrast=1.08"
                elif fx_mode == "RGB Split ساده (Glitch رنگی)":
                    vf += ",chromashift=cbh=3:cbv=0:crh=-3:crv=0"
                if use_flash:
                    vf += ",eq=brightness=0.10"

                if asset_type == "video":
                    # Loop short source clips to fill their assigned segment instead of
                    # rejecting them. This avoids forcing users to find/download longer footage.
                    vf += f",trim=duration={per_clip:.3f},setpts=PTS-STARTPTS"
                    input_args = ["-stream_loop", "-1", "-i", str(src), "-t", f"{per_clip:.3f}"]
                else:
                    frames = max(1, round(per_clip * 24))
                    # Gentle luxury-product camera movement: subtle 3-4% zoom, not an aggressive push-in.
                    if i % 3 == 0:
                        zoom_expr = "min(zoom+0.00022,1.04)"
                        x_expr = "iw/2-(iw/zoom/2)"
                    elif i % 3 == 1:
                        zoom_expr = "if(eq(on,0),1.0,min(zoom+0.00018,1.035))"
                        x_expr = "iw/2-(iw/zoom/2)+4*sin(on/90)"
                    else:
                        zoom_expr = "if(eq(on,0),1.0,min(zoom+0.00016,1.03))"
                        x_expr = "iw/2-(iw/zoom/2)-4*sin(on/100)"
                    vf += f",zoompan=z='{zoom_expr}':d=1:x='{x_expr}':y='ih/2-(ih/zoom/2)':s={output_w}x{output_h}:fps=24,trim=duration={per_clip:.3f},setpts=PTS-STARTPTS"
                    input_args = ["-loop", "1", "-framerate", "24", "-i", str(src), "-t", f"{per_clip:.3f}"]

                # Optional dip-to-black transition on every shot; clean cuts remain the default.
                if transition == "محو شدن از سیاهی":
                    fade_len = min(0.35, per_clip / 4)
                    vf += f",fade=t=in:st=0:d={fade_len:.3f},fade=t=out:st={max(0, per_clip-fade_len):.3f}:d={fade_len:.3f}"
                vf += ",format=yuv420p"

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
            music_input_index = None
            if music_ready:
                cmd += ["-stream_loop", "-1", "-i", str(music_path)]
                music_input_index = 2 if narration else 1

            video_filters = [f"fade=t=in:st=0:d=0.7", f"fade=t=out:st={max(0, duration-0.8):.3f}:d=0.8"]
            if motion_graphics and (mg_title.strip() or mg_subtitle.strip() or mg_cta.strip()):
                # Use text files to avoid fragile FFmpeg escaping for user-entered text.
                font_candidates = [
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
                    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
                ]
                font_file = next((p for p in font_candidates if Path(p).exists()), None)
                if font_file:
                    title_file = work / "mg_title.txt"
                    subtitle_file = work / "mg_subtitle.txt"
                    cta_file = work / "mg_cta.txt"
                    title_file.write_text(mg_title.strip(), encoding="utf-8")
                    subtitle_file.write_text(mg_subtitle.strip(), encoding="utf-8")
                    cta_file.write_text(mg_cta.strip(), encoding="utf-8")
                    font_arg = font_file.replace("\\", "/").replace(":", "\\:")
                    # Animated title card: gentle upward entrance, opacity fade, accent rule and CTA pill.
                    if mg_style.startswith("لوکس"):
                        title_y = "h*0.70"
                        subtitle_y = "h*0.70+text_h+18"
                        cta_y = "h*0.70+text_h+72"
                        x_expr = "(w-text_w)/2"
                        box_x = "w*0.24"
                        box_w = "w*0.52"
                    elif mg_style.startswith("مدرن"):
                        title_y = "(h-text_h)/2"
                        subtitle_y = "(h-text_h)/2+text_h+22"
                        cta_y = "(h-text_h)/2+text_h+76"
                        x_expr = "(w-text_w)/2"
                        box_x = "w*0.30"
                        box_w = "w*0.40"
                    else:
                        title_y = "h*0.78"
                        subtitle_y = "h*0.78+text_h+14"
                        cta_y = "h*0.78+text_h+58"
                        x_expr = "w*0.09"
                        box_x = "w*0.09"
                        box_w = "w*0.34"
                    alpha_expr = "if(lt(t,0.7),t/0.7,if(gt(t," + str(max(0, duration-0.7)) + "),(" + str(duration) + "-t)/0.7,1))"
                    rise_expr = "12*(1-min(t/0.7,1))"
                    common = f":fontfile='{font_arg}':expansion=none:shadowcolor=black@0.65:shadowx=2:shadowy=2"
                    video_filters.append(f"drawbox=x={box_x}:y=h*0.68:w={box_w}:h=3:color=0xD6B46A@0.95:t=fill:enable='between(t,0.15,{duration-0.15})'")
                    if mg_title.strip():
                        video_filters.append(f"drawtext=textfile='{title_file.as_posix()}':x={x_expr}:y={title_y}-{rise_expr}:fontsize=h*0.034:fontcolor=white:alpha='{alpha_expr}'{common}")
                    if mg_subtitle.strip():
                        video_filters.append(f"drawtext=textfile='{subtitle_file.as_posix()}':x=(w-text_w)/2:y={subtitle_y}:fontsize=h*0.018:fontcolor=0xE8D8B8:alpha='{alpha_expr}'{common}")
                    if mg_cta.strip():
                        video_filters.append(f"drawbox=x=(w-min(w*0.34,360))/2:y={cta_y}:w=min(w*0.34,360):h=48:color=0xD6B46A@0.92:t=fill:enable='between(t,0.5,{duration-0.2})'")
                        video_filters.append(f"drawtext=textfile='{cta_file.as_posix()}':x=(w-text_w)/2:y={cta_y}+14:fontsize=h*0.015:fontcolor=black:alpha='{alpha_expr}'{common}")
                else:
                    st.warning("فونت مناسب برای موشن‌گرافیک در محیط رندر پیدا نشد؛ تیزر بدون نوشته‌های متحرک ساخته می‌شود.")
            cmd += ["-vf", ",".join(video_filters), "-map", "0:v:0"]

            audio_fade = f"afade=t=in:st=0:d=0.35,afade=t=out:st={max(0, duration-0.8):.3f}:d=0.8"
            if narration and music_ready:
                graph = (
                    f"[1:a]volume={voice_level/100:.2f}[v];"
                    f"[{music_input_index}:a]volume={music_level/100:.2f}[m];"
                    f"[v][m]amix=inputs=2:duration=longest:dropout_transition=2,"
                    f"atrim=duration={duration},{audio_fade}[a]"
                )
                cmd += ["-filter_complex", graph, "-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
            elif narration:
                cmd += ["-map", "1:a:0", "-af",
                        f"aresample=48000,apad,atrim=duration={duration},volume={voice_level/100:.2f},{audio_fade}",
                        "-c:a", "aac", "-b:a", "160k"]
            elif music_ready:
                cmd += ["-map", f"{music_input_index}:a:0", "-af",
                        f"aresample=48000,apad,atrim=duration={duration},volume={music_level/100:.2f},lowpass=f=15000,alimiter=limit=0.92,{audio_fade}",
                        "-c:a", "aac", "-b:a", "160k"]
            else:
                st.warning("تیزر بدون صدا رندر می‌شود؛ برای خروجی صوتی، موسیقی یا گویندگی بارگذاری کن.")

            cmd += ["-t", str(duration), "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "23" if quality == "1080p متعادل" else "26",
                    "-pix_fmt", "yuv420p"]
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
st.caption("نکته: موشن‌گرافیک این نسخه از قالب‌های متحرک آماده (تیتر، زیرتیتر، خط گرافیکی و دکمه دعوت به اقدام) ساخته می‌شود؛ این قابلیت تولید مولدِ هوش مصنوعی یا موشن‌گرافیک سه‌بعدی نیست. برای تولید AI واقعی باید بعداً سرویس و API جداگانه متصل شود. موسیقی پیش‌فرض Wikimedia در صورت محدودیت سرور ممکن است در دسترس نباشد.")
