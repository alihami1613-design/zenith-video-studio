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

st.subheader("۵ — نمای ترتیب زمانی")
clips=sorted(st.session_state.timeline_video,key=lambda x:x.get("start",0))
if clips:
    total=max((c.get("start",0)+c.get("duration",0) for c in clips),default=0)
    st.metric("مدت تخمینی تایم‌لاین",f"{total:.1f} ثانیه")
    for c in clips:
        st.write(f"{c['name']} · آغاز {c.get('start',0):.1f}s · طول {c.get('duration',0):.1f}s")
else:
    st.info("برای آغاز، ویدئو وارد کنید.")

st.caption("استخراج کلیپ به MP4 با FFmpeg پیاده‌سازی شده؛ رندر کل تایم‌لاین، همگام‌سازی چند ترک و افکت‌ها هنوز در مراحل بعدی هستند.")
