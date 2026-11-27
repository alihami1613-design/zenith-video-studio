import streamlit as st
import subprocess
import tempfile
from pathlib import Path

st.set_page_config(page_title="ZENITH Timeline", page_icon="🎞️", layout="wide")
st.title("🎞️ ZENITH — Timeline Editor")
st.caption("ویرایشگر مستقل و آزمایشی؛ پردازش سبک برای سازگاری با سیستم‌های معمولی.")
st.warning("این صفحه مستقل است و به صفحات Documentary_Editor و Auto_Studio دست نمی‌زند.")

if "timeline_video" not in st.session_state:
    st.session_state.timeline_video = []
if "timeline_audio" not in st.session_state:
    st.session_state.timeline_audio = []

def move_clip(index, direction):
    clips = st.session_state.timeline_video
    target = index + direction
    if 0 <= target < len(clips):
        clips[index], clips[target] = clips[target], clips[index]
        # Keep a simple sequential timeline after reordering.
        cursor = 0.0
        for item in clips:
            item["start"] = cursor
            item["duration"] = max(.1, float(item.get("trim_out", 5))-float(item.get("trim_in", 0)))
            cursor += item["duration"]

st.subheader("۱ — وارد کردن رسانه")
videos = st.file_uploader("ویدئوها (V1)", type=["mp4","mov","mkv","avi","webm"], accept_multiple_files=True, key="tl_v")
audios = st.file_uploader("فایل‌های صوتی", type=["mp3","wav","m4a","aac","ogg"], accept_multiple_files=True, key="tl_a")
if st.button("افزودن رسانه"):
    for f in videos or []:
        if f.name not in [x["name"] for x in st.session_state.timeline_video]:
            st.session_state.timeline_video.append({"name":f.name,"size":f.size,"duration":5.0,"start":0.0,"trim_in":0.0,"trim_out":5.0,"source":f})
    for f in audios or []:
        if f.name not in [x["name"] for x in st.session_state.timeline_audio]:
            st.session_state.timeline_audio.append({"name":f.name,"size":f.size,"source":f})
    st.success("رسانه اضافه شد.")

st.divider()
st.subheader("۲ — تنظیم کلیپ‌ها")
for i, clip in enumerate(st.session_state.timeline_video):
    with st.expander(f"V1 · {clip['name']}", expanded=False):
        col1,col2,col3 = st.columns(3)
        clip["trim_in"] = col1.number_input("شروع برش (ثانیه)", min_value=0.0, value=float(clip.get("trim_in",0)), step=.1, key=f"tin{i}")
        clip["trim_out"] = col2.number_input("پایان برش (ثانیه)", min_value=.1, value=max(float(clip.get("trim_out",5)),float(clip.get("trim_in",0))+.1), step=.1, key=f"tout{i}")
        clip["start"] = col3.number_input("شروع روی تایم‌لاین (ثانیه)", min_value=0.0, value=float(clip.get("start",0)), step=.5, key=f"vstart{i}")
        if clip["trim_out"] > clip["trim_in"]:
            clip["duration"] = clip["trim_out"]-clip["trim_in"]
            st.write(f"مدت انتخابی: {clip['duration']:.2f} ثانیه")
        else:
            st.error("پایان برش باید از شروع بزرگ‌تر باشد.")
        left,right = st.columns(2)
        if left.button("⬆️ جابه‌جایی به بالا", key=f"up{i}"):
            move_clip(i,-1); st.rerun()
        if right.button("⬇️ جابه‌جایی به پایین", key=f"down{i}"):
            move_clip(i,1); st.rerun()
        if st.button("حذف کلیپ",key=f"delete{i}"):
            st.session_state.timeline_video.pop(i); st.rerun()

st.subheader("۳ — پیش‌نمایش رسانه")
if st.session_state.timeline_video:
    vi = st.selectbox("پیش‌نمایش ویدئو",range(len(st.session_state.timeline_video)),format_func=lambda n:st.session_state.timeline_video[n]["name"],key="preview_v")
    st.video(st.session_state.timeline_video[vi]["source"],start_time=int(st.session_state.timeline_video[vi].get("trim_in",0)))
if st.session_state.timeline_audio:
    ai = st.selectbox("پیش‌نمایش صدا",range(len(st.session_state.timeline_audio)),format_func=lambda n:st.session_state.timeline_audio[n]["name"],key="preview_a")
    st.audio(st.session_state.timeline_audio[ai]["source"])

st.subheader("۴ — برش و خروجی مستقل")
st.caption("فایل اصلی تغییر نمی‌کند؛ یک فایل جدید ساخته می‌شود.")
if st.session_state.timeline_video:
    idx=st.selectbox("انتخاب کلیپ برای برش",range(len(st.session_state.timeline_video)),format_func=lambda n:st.session_state.timeline_video[n]["name"],key="trim_export_select")
    clip=st.session_state.timeline_video[idx]
    if st.button("استخراج بخش انتخابی"):
        try:
            import imageio_ffmpeg
            ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
            with tempfile.TemporaryDirectory() as td:
                inp=Path(td)/("input"+(Path(clip["name"]).suffix or ".mp4")); out=Path(td)/"trimmed.mp4"
                inp.write_bytes(clip["source"].getvalue())
                cmd=[ffmpeg,"-y","-ss",str(clip["trim_in"]),"-i",str(inp),"-t",str(clip["trim_out"]-clip["trim_in"]),"-c:v","libx264","-preset","ultrafast","-crf","23","-c:a","aac","-movflags","+faststart",str(out)]
                result=subprocess.run(cmd,capture_output=True,text=True,timeout=240)
                if result.returncode or not out.exists(): st.error("برش ناموفق بود؛ احتمالاً کدک یا فرمت پشتیبانی نشده.")
                else:
                    data=out.read_bytes(); st.video(data)
                    st.download_button("دانلود کلیپ برش‌خورده",data=data,file_name=Path(clip["name"]).stem+"_trim.mp4",mime="video/mp4")
        except Exception as e: st.error(f"خطا: {e}")

st.subheader("۵ — تنظیم صدا")
video_gain=st.slider("صدای کلیپ‌های اصلی",0.0,2.0,1.0,.1,key="video_gain")
audio_gain=st.slider("صدای فایل صوتی انتخابی",0.0,2.0,.35,.05,key="audio_gain")
selected_audio_idx=None
if st.session_state.timeline_audio:
    selected_audio_idx=st.selectbox("انتخاب موسیقی/صدا",range(len(st.session_state.timeline_audio)),format_func=lambda n:st.session_state.timeline_audio[n]["name"],key="mix_audio_select")

st.subheader("۶ — ترکیب کلیپ‌ها")
st.caption("کلیپ‌ها طبق ترتیب شروع به هم متصل می‌شوند. خروجی 720p و 30fps با تنظیمات سبک ساخته می‌شود. فاصله‌های خالی و هم‌پوشانی هنوز در رندر اعمال نمی‌شوند.")
if len(st.session_state.timeline_video)>=2 and st.button("رندر ویدئوی ترکیبی"):
    try:
        import imageio_ffmpeg
        ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
        ordered=sorted(st.session_state.timeline_video,key=lambda x:x.get("start",0))
        with tempfile.TemporaryDirectory() as td:
            td=Path(td); segments=[]; progress=st.progress(0); status=st.empty()
            for i,c in enumerate(ordered):
                length=float(c["trim_out"])-float(c["trim_in"])
                if length<=0: raise ValueError("یک کلیپ نقطه برش نامعتبر دارد.")
                src=td/f"src_{i}{Path(c['name']).suffix or '.mp4'}"; seg=td/f"seg_{i}.mp4"
                src.write_bytes(c["source"].getvalue()); status.write(f"پردازش کلیپ {i+1}/{len(ordered)}")
                probe=subprocess.run([ffmpeg,"-i",str(src)],capture_output=True,text=True,timeout=60)
                has_audio="Audio:" in (probe.stderr or "")
                cmd=[ffmpeg,"-y","-ss",str(c["trim_in"]),"-i",str(src)]
                if not has_audio:
                    cmd += ["-f","lavfi","-i","anullsrc=channel_layout=stereo:sample_rate=44100"]
                cmd += ["-t",str(length),"-map","0:v:0"]
                cmd += (["-map","0:a:0?"] if has_audio else ["-map","1:a:0"])
                cmd += ["-vf","scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=30","-c:v","libx264","-preset","ultrafast","-crf","24","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k","-ar","44100","-ac","2","-shortest","-movflags","+faststart",str(seg)]
                rr=subprocess.run(cmd,capture_output=True,text=True,timeout=300)
                if rr.returncode or not seg.exists():
                    detail=(rr.stderr or "نامشخص")[-1200:]
                    raise RuntimeError(f"پردازش کلیپ {i+1} ناموفق شد: {detail}")
                segments.append(seg); progress.progress((i+1)/len(ordered))
            listing=td/"concat.txt"
            listing.write_text("\n".join("file '"+p.as_posix()+"'" for p in segments),encoding="utf-8")
            joined=td/"joined.mp4"
            rr=subprocess.run([ffmpeg,"-y","-f","concat","-safe","0","-i",str(listing),"-c","copy","-movflags","+faststart",str(joined)],capture_output=True,text=True,timeout=300)
            if rr.returncode or not joined.exists():
                detail=(rr.stderr or "نامشخص")[-1200:]
                raise RuntimeError(f"اتصال کلیپ‌ها ناموفق شد: {detail}")
            final=joined
            if selected_audio_idx is not None:
                aud=td/("music"+Path(st.session_state.timeline_audio[selected_audio_idx]["name"]).suffix)
                aud.write_bytes(st.session_state.timeline_audio[selected_audio_idx]["source"].getvalue())
                mixed=td/"ZENITH_mixed.mp4"
                filt=f"[0:a]volume={video_gain}[va];[1:a]volume={audio_gain}[ma];[va][ma]amix=inputs=2:duration=first:dropout_transition=2[a]"
                rr=subprocess.run([ffmpeg,"-y","-i",str(joined),"-i",str(aud),"-filter_complex",filt,"-map","0:v","-map","[a]","-c:v","copy","-c:a","aac","-b:a","192k","-shortest","-movflags","+faststart",str(mixed)],capture_output=True,text=True,timeout=300)
                if rr.returncode or not mixed.exists():
                    detail=(rr.stderr or "نامشخص")[-1600:]
                    raise RuntimeError(f"ترکیب صدا ناموفق شد: {detail}")
                final=mixed
            data=final.read_bytes(); status.success("رندر آماده شد.")
            st.video(data); st.download_button("دانلود ویدئوی نهایی",data=data,file_name="ZENITH_combined.mp4",mime="video/mp4")
    except Exception as e: st.error(f"خطا در رندر: {e}")
elif st.session_state.timeline_video and len(st.session_state.timeline_video)<2:
    st.info("برای رندر ترکیبی، حداقل دو کلیپ وارد کنید.")

st.subheader("۷ — نمای گرافیکی تایم‌لاین")
ordered=sorted(st.session_state.timeline_video,key=lambda x:x.get("start",0))
if ordered:
    total=max((float(c.get("start",0))+float(c.get("duration",0)) for c in ordered),default=0)
    st.metric("مدت تخمینی",f"{total:.1f} ثانیه")
    for j,c in enumerate(ordered):
        start=max(0,float(c.get("start",0))); duration=max(.1,float(c.get("duration",0)))
        if total:
            left=min(100,start/total*100); width=max(1,min(100-left,duration/total*100))
            st.markdown(f'<div style="font-size:13px;margin-top:7px">{j+1} · {c["name"]} ({start:.1f}–{start+duration:.1f}s)</div><div style="background:rgba(120,120,120,.16);height:26px;border-radius:6px;position:relative;overflow:hidden"><div style="position:absolute;left:{left:.2f}%;width:{width:.2f}%;height:26px;background:#4c83c3;border-radius:6px;color:white;text-align:center;line-height:26px;font-size:12px;overflow:hidden">V1 · {duration:.1f}s</div></div>',unsafe_allow_html=True)
else:
    st.info("ویدئو اضافه کنید تا تایم‌لاین نمایش داده شود.")

st.caption("امکانات موجود: افزودن چند ویدئو و صدا، پیش‌نمایش، برش، جابه‌جایی کلیپ، تنظیم زمان شروع، نمای گرافیکی، اتصال کلیپ‌ها، کنترل حجم صدا و خروجی MP4. امکانات پیشرفته مانند چندلایه، انتقال‌های تصویری، افکت و زمان‌بندی مستقل ترک‌ها در توسعه بعدی.")
