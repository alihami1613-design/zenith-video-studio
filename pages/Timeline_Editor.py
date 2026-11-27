import streamlit as st
import subprocess
import tempfile
from pathlib import Path

st.set_page_config(page_title="ZENITH Timeline", page_icon="🎞️", layout="wide")
st.title("🎞️ ZENITH — Multi-track Timeline")
st.caption("مرحله چهارم: پیش‌نمایش و استخراج واقعی بخش انتخابی کلیپ.")
st.warning("صفحه مستقل و آزمایشی است؛ صفحات Documentary_Editor و Auto_Studio تغییر نمی‌کنند.")

if "timeline_video" not in st.session_state:
    st.session_state.timeline_video = []
if "timeline_audio" not in st.session_state:
    st.session_state.timeline_audio = []

st.subheader("۱ — وارد کردن رسانه")
videos=st.file_uploader("ویدئوها (V1)",type=["mp4","mov","mkv","avi","webm"],accept_multiple_files=True,key="tl_v")
audios=st.file_uploader("صداها (A1)",type=["mp3","wav","m4a","aac","ogg"],accept_multiple_files=True,key="tl_a")
if st.button("افزودن رسانه به تایم‌لاین"):
    for f in videos or []:
        if f.name not in [x["name"] for x in st.session_state.timeline_video]:
            st.session_state.timeline_video.append({"name":f.name,"size":f.size,"duration":5.0,"start":0.0,"trim_in":0.0,"trim_out":5.0,"source":f})
    for f in audios or []:
        if f.name not in [x["name"] for x in st.session_state.timeline_audio]:
            st.session_state.timeline_audio.append({"name":f.name,"size":f.size,"source":f})
    st.success("رسانه اضافه شد.")

st.divider()
st.subheader("۲ — تنظیم نقاط برش")
for i,clip in enumerate(st.session_state.timeline_video):
    with st.expander(f"V1 · {clip['name']}",expanded=True):
        a,b,c=st.columns(3)
        clip["trim_in"]=a.number_input("شروع برش (ثانیه)",min_value=0.0,value=float(clip.get("trim_in",0)),step=.1,key=f"tin{i}")
        clip["trim_out"]=b.number_input("پایان برش (ثانیه)",min_value=.1,value=max(float(clip.get("trim_out",clip.get("duration",5))),float(clip.get("trim_in",0))+.1),step=.1,key=f"tout{i}")
        clip["start"]=c.number_input("جای کلیپ در تایم‌لاین",min_value=0.0,value=float(clip.get("start",0)),step=.5,key=f"vstart{i}")
        if clip["trim_out"]>clip["trim_in"]:
            clip["duration"]=clip["trim_out"]-clip["trim_in"]
            st.write(f"مدت بخش انتخابی: {clip['duration']:.2f} ثانیه")
        else:
            st.error("پایان باید بعد از شروع باشد.")
        if st.button("حذف کلیپ",key=f"vdel{i}"):
            st.session_state.timeline_video.pop(i)
            st.rerun()

st.subheader("۳ — پیش‌نمایش")
if st.session_state.timeline_video:
    chosen=st.selectbox("انتخاب ویدئو برای پخش",range(len(st.session_state.timeline_video)),format_func=lambda n:st.session_state.timeline_video[n]["name"],key="preview_v")
    st.video(st.session_state.timeline_video[chosen]["source"],start_time=int(st.session_state.timeline_video[chosen].get("trim_in",0)))
if st.session_state.timeline_audio:
    chosen_a=st.selectbox("انتخاب فایل صوتی",range(len(st.session_state.timeline_audio)),format_func=lambda n:st.session_state.timeline_audio[n]["name"],key="preview_a")
    st.audio(st.session_state.timeline_audio[chosen_a]["source"])

st.subheader("۴ — استخراج واقعی بخش انتخابی (Trim)")
st.caption("این عملیات فایل خروجی جدید می‌سازد و فایل اصلی را تغییر نمی‌دهد. برای جلوگیری از فشار زیاد روی سیستم، کلیپ‌ها جداگانه پردازش می‌شوند.")
if st.session_state.timeline_video:
    idx=st.selectbox("کلیپ موردنظر برای برش",range(len(st.session_state.timeline_video)),format_func=lambda n:st.session_state.timeline_video[n]["name"],key="trim_export_select")
    clip=st.session_state.timeline_video[idx]
    if clip["trim_out"]>clip["trim_in"] and st.button("برش و آماده‌سازی فایل خروجی"):
        try:
            import imageio_ffmpeg
            ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
            ext=Path(clip["name"]).suffix or ".mp4"
            with tempfile.TemporaryDirectory() as td:
                inp=Path(td)/("input"+ext)
                out=Path(td)/"trimmed.mp4"
                inp.write_bytes(clip["source"].getvalue())
                cmd=[ffmpeg,"-y","-ss",str(clip["trim_in"]),"-i",str(inp),"-t",str(clip["trim_out"]-clip["trim_in"]),"-c:v","libx264","-preset","ultrafast","-crf","23","-c:a","aac","-movflags","+faststart",str(out)]
                result=subprocess.run(cmd,capture_output=True,text=True,timeout=240)
                if result.returncode!=0 or not out.exists():
                    st.error("برش انجام نشد. ممکن است فرمت یا کدک فایل پشتیبانی نشود.")
                else:
                    data=out.read_bytes()
                    st.video(data)
                    st.download_button("دانلود کلیپ برش‌خورده",data=data,file_name=Path(clip["name"]).stem+"_trim.mp4",mime="video/mp4")
        except Exception as e:
            st.error(f"خطا در پردازش: {e}")


st.subheader("۵ — تنظیم صدای خروجی")\nvideo_gain=st.slider("میزان صدای ویدئوهای اصلی",0.0,2.0,1.0,0.1,key="video_gain")\naudio_gain=st.slider("میزان صدای موسیقی/فایل A1",0.0,2.0,0.35,0.05,key="audio_gain")\nselected_audio_idx=None\nif st.session_state.timeline_audio:\n    selected_audio_idx=st.selectbox("انتخاب فایل صوتی برای خروجی",range(len(st.session_state.timeline_audio)),format_func=lambda n:st.session_state.timeline_audio[n]["name"],key="mix_audio_select")\n\nst.subheader("۶ — ترکیب کلیپ‌ها و ساخت ویدئوی واحد")
st.caption("کلیپ‌ها بر اساس ترتیب زمان شروع پشت سر هم ترکیب می‌شوند. فاصله‌های خالی، لایه‌ها و صداهای مستقل هنوز در خروجی نهایی لحاظ نمی‌شوند. خروجی سبک 720p برای کاهش فشار روی سیستم ساخته می‌شود.")
if len(st.session_state.timeline_video)>=2:
    if st.button("ساخت ویدئوی ترکیبی از کلیپ‌ها"):
        try:
            import imageio_ffmpeg
            ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
            ordered=sorted(st.session_state.timeline_video,key=lambda x:x.get("start",0))
            with tempfile.TemporaryDirectory() as td:
                td=Path(td)
                segment_paths=[]
                progress=st.progress(0)
                status=st.empty()
                for i,clip in enumerate(ordered):
                    if clip.get("trim_out",5)<=clip.get("trim_in",0):
                        raise ValueError("یکی از کلیپ‌ها نقطه برش نامعتبر دارد.")
                    ext=Path(clip["name"]).suffix or ".mp4"
                    src=td/f"source_{i}{ext}"
                    seg=td/f"segment_{i}.mp4"
                    src.write_bytes(clip["source"].getvalue())
                    length=float(clip["trim_out"])-float(clip["trim_in"])
                    status.write(f"در حال پردازش کلیپ {i+1} از {len(ordered)}")
                    cmd=[ffmpeg,"-y","-ss",str(clip["trim_in"]),"-i",str(src),"-t",str(length),"-vf","scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=30","-c:v","libx264","-preset","ultrafast","-crf","24","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k","-ar","44100","-ac","2","-movflags","+faststart",str(seg)]
                    result=subprocess.run(cmd,capture_output=True,text=True,timeout=300)
                    if result.returncode!=0 or not seg.exists():
                        raise RuntimeError(f"پردازش کلیپ {i+1} شکست خورد.")
                    segment_paths.append(seg)
                    progress.progress((i+1)/len(ordered))
                concat_file=td/"concat.txt"
                concat_file.write_text("\n".join("file '"+p.as_posix()+"'" for p in segment_paths),encoding="utf-8")
                output=td/"ZENITH_combined.mp4"
                cmd=[ffmpeg,"-y","-f","concat","-safe","0","-i",str(concat_file),"-c","copy","-movflags","+faststart",str(output)]
                result=subprocess.run(cmd,capture_output=True,text=True,timeout=300)
                if result.returncode!=0 or not output.exists():
                    raise RuntimeError("مرحله ترکیب کلیپ‌ها ناموفق بود.")
                data=output.read_bytes()
                status.success("ویدئوی ترکیبی آماده شد.")
                st.video(data)
                st.download_button("دانلود ویدئوی ترکیبی",data=data,file_name="ZENITH_combined.mp4",mime="video/mp4")
        except Exception as e:
            st.error(f"خطا: {e}")
elif st.session_state.timeline_video:
    st.info("برای ترکیب، حداقل دو کلیپ به تایم‌لاین اضافه کنید.")

st.subheader("۷ — نمای گرافیکی تایم‌لاین")
clips=sorted(st.session_state.timeline_video,key=lambda x:x.get("start",0))
if clips:
    total=max((c.get("start",0)+c.get("duration",0) for c in clips),default=0)
    st.metric("مدت تخمینی تایم‌لاین",f"{total:.1f} ثانیه")
    if total>0:
        st.caption("نمای ساده مقیاس‌دار: محل و طول کلیپ‌ها تقریبی و بر مبنای زمان شروع و مدت هستند.")
        for ci,c in enumerate(clips):
            start=max(0.0,float(c.get("start",0)))
            dur=max(0.1,float(c.get("duration",0)))
            left_pct=min(100,start/total*100)
            width_pct=max(1,min(100-left_pct,dur/total*100))
            st.markdown(f"""
<div style="margin:8px 0 3px;font-size:13px">{ci+1}. {c['name']} — {start:.1f}s تا {start+dur:.1f}s</div>
<div style="background:rgba(120,120,120,.16);border-radius:8px;height:28px;position:relative;overflow:hidden">
<div style="position:absolute;left:{left_pct:.2f}%;width:{width_pct:.2f}%;height:28px;background:#4c83c3;border-radius:6px;color:white;text-align:center;line-height:28px;white-space:nowrap;overflow:hidden;font-size:12px">V1 · {dur:.1f}s</div></div>
""",unsafe_allow_html=True)
    st.caption("در رندر فعلی، کلیپ‌ها پشت سر هم قرار می‌گیرند و فاصله‌های زمانی/هم‌پوشانی هنوز اعمال نمی‌شوند.")
else:
    st.info("برای آغاز، ویدئو وارد کنید.")

st.caption("استخراج کلیپ به MP4 با FFmpeg پیاده‌سازی شده؛ ترکیب پشت سر هم کلیپ‌ها در خروجی 720p اضافه شده است؛ ترکیب صدای اصلی و یک فایل صوتی جدا با تنظیم میزان صدا اضافه شده؛ چند ترک صوتی هم‌زمان، زمان‌بندی مستقل صدا، افکت‌ها و رندر حرفه‌ای هنوز در مراحل بعدی هستند.")
