import streamlit as st

st.set_page_config(page_title="ZENITH Timeline", page_icon="🎞️", layout="wide")
st.title("🎞️ ZENITH — Multi-track Timeline")
st.caption("مرحله دوم: تعیین نقاط برش (Trim) و مدت استفاده از هر کلیپ.")
st.warning("این صفحه آزمایشی و مستقل است و به Documentary_Editor یا Auto_Studio دست نمی‌زند.")

if "timeline_video" not in st.session_state:
    st.session_state.timeline_video = []
if "timeline_audio" not in st.session_state:
    st.session_state.timeline_audio = []

st.subheader("۱ — وارد کردن رسانه")
videos = st.file_uploader("ویدئوها (ترک V1)", type=["mp4","mov","mkv","avi","webm"], accept_multiple_files=True, key="tl_v")
audios = st.file_uploader("صداها (ترک A1)", type=["mp3","wav","m4a","aac","ogg"], accept_multiple_files=True, key="tl_a")

if st.button("افزودن رسانه به تایم‌لاین"):
    for f in videos or []:
        if f.name not in [x["name"] for x in st.session_state.timeline_video]:
            st.session_state.timeline_video.append({"name":f.name,"size":f.size,"duration":5.0,"start":0.0,"trim_in":0.0,"trim_out":5.0,"source":f})
    for f in audios or []:
        if f.name not in [x["name"] for x in st.session_state.timeline_audio]:
            st.session_state.timeline_audio.append({"name":f.name,"size":f.size,"source":f})
    st.success("رسانه‌ها به تایم‌لاین اضافه شدند.")

st.divider()
st.subheader("۲ — تنظیم کلیپ و نقاط برش")
st.markdown("**V1 — ترک ویدئو**")
if not st.session_state.timeline_video:
    st.info("هنوز کلیپی به ترک V1 اضافه نشده.")
else:
    for i, clip in enumerate(st.session_state.timeline_video):
        with st.expander(f"کلیپ {i+1}: {clip['name']}", expanded=True):
            c1,c2,c3,c4=st.columns(4)
            clip["trim_in"]=c1.number_input("برش از ابتدای فایل (ثانیه)",min_value=0.0,value=float(clip.get("trim_in",0.0)),step=0.1,key=f"tin{i}")
            clip["trim_out"]=c2.number_input("پایان بخش انتخابی (ثانیه)",min_value=0.1,value=max(float(clip.get("trim_out",clip.get("duration",5.0))),float(clip.get("trim_in",0.0))+0.1),step=0.1,key=f"tout{i}")
            clip["start"]=c3.number_input("جای کلیپ روی تایم‌لاین (ثانیه)",min_value=0.0,value=float(clip["start"]),step=0.5,key=f"vstart{i}")
            c4.write(f"حجم: {clip['size']/1024/1024:.1f} MB")
            if clip["trim_out"] <= clip["trim_in"]:
                st.error("نقطه پایان برش باید از نقطه شروع بزرگ‌تر باشد.")
            else:
                clip["duration"]=clip["trim_out"]-clip["trim_in"]
                st.info(f"بخش انتخاب‌شده: {clip['trim_in']:.1f} تا {clip['trim_out']:.1f} ثانیه | مدت: {clip['duration']:.1f} ثانیه")
            if st.button("حذف این کلیپ",key=f"vdel{i}"):
                st.session_state.timeline_video.pop(i)
                st.rerun()

st.markdown("**A1 — ترک صوتی**")
if not st.session_state.timeline_audio:
    st.info("هنوز فایل صوتی به ترک A1 اضافه نشده.")
else:
    for i,audio in enumerate(st.session_state.timeline_audio):
        st.write(f"{i+1}. {audio['name']} — {audio['size']/1024/1024:.1f} MB")
        if st.button("حذف صدا",key=f"adel{i}"):
            st.session_state.timeline_audio.pop(i)
            st.rerun()

st.divider()
st.subheader("۳ — ترتیب و مدت تایم‌لاین")
clips=sorted(st.session_state.timeline_video,key=lambda x:x["start"])
if clips:
    total=max((c["start"]+max(0.0,c.get("duration",0.0)) for c in clips),default=0)
    st.metric("مدت تخمینی تایم‌لاین",f"{total:.1f} ثانیه")
    for c in clips:
        st.markdown(f"**{c['name']}** · شروع {c['start']:.1f}s · بخش فایل {c.get('trim_in',0):.1f}–{c.get('trim_out',c['duration']):.1f}s · مدت روی تایم‌لاین {c['duration']:.1f}s")
        st.progress(min(1.0,(c["duration"]/total)) if total else 0)
else:
    st.caption("با افزودن کلیپ‌ها، ترتیب و مدت آن‌ها نمایش داده می‌شود.")

st.caption("در این مرحله، نقاط برش و مدت انتخابی ثبت و در محاسبات تایم‌لاین لحاظ می‌شوند. برش فیزیکی فایل، پیش‌نمایش و رندر نهایی هنوز در مراحل بعد اضافه می‌شوند.")
