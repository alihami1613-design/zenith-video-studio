import json
import re
from datetime import datetime
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "projects"
DATA_DIR.mkdir(exist_ok=True)

st.set_page_config(page_title="ZENITH Video Studio", page_icon="🎬", layout="wide")

st.markdown("""
<style>
html, body, [class*="css"] { direction: rtl; text-align: right; }
.block-container { max-width: 1150px; padding-top: 2rem; }
div[data-testid="stTextInput"] input, div[data-testid="stTextArea"] textarea { direction: rtl; }
</style>
""", unsafe_allow_html=True)

st.title("🎬 استودیوی تولید خودکار ویدئو")
st.caption("نسخه آزمایشی ۰.۱ — مدیریت پروژه، مراحل تولید و تأیید انسانی")

STAGES = [
    ("idea", "۱. ایده و زاویه روایت"),
    ("research", "۲. تحقیق و منابع"),
    ("script", "۳. متن گویندگی"),
    ("storyboard", "۴. سناریوی تصویری و پرامپت‌ها"),
    ("assets", "۵. تصاویر، ویدئوها و صدا"),
    ("edit", "۶. تدوین و صداگذاری"),
    ("export", "۷. بازبینی و خروجی نهایی"),
]

def slugify(s):
    s = re.sub(r"[^\w\-]+", "-", s.strip(), flags=re.UNICODE).strip("-")
    return (s[:48] or "project")

def project_path(pid):
    return DATA_DIR / f"{pid}.json"

def load_projects():
    items = []
    for p in sorted(DATA_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            items.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return items

def save_project(obj):
    project_path(obj["id"]).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

projects = load_projects()
with st.sidebar:
    st.header("پروژه‌ها")
    selected = st.selectbox(
        "انتخاب پروژه",
        options=["پروژه جدید"] + [p["id"] for p in projects],
        format_func=lambda x: "پروژه جدید" if x == "پروژه جدید" else next((p["title"] for p in projects if p["id"] == x), x)
    )

if selected == "پروژه جدید":
    st.subheader("ساخت پروژه جدید")
    with st.form("new_project"):
        title = st.text_input("عنوان پروژه", placeholder="مثلاً The Secret Life Inside You")
        content_type = st.radio("نوع محتوا", ["مستند بلند", "ویدئوی کوتاه"], horizontal=True)
        brand = st.selectbox("کانال / برند", ["ZENITH BEYOND", "ARTNOVA", "سایر"])
        language = st.selectbox("زبان خروجی", ["English", "Persian", "دو زبانه"])
        target = st.text_area("موضوع یا ایده اولیه", placeholder="موضوع را در چند جمله توضیح بده...")
        submitted = st.form_submit_button("ایجاد پروژه")
    if submitted:
        if not title.strip() or not target.strip():
            st.error("عنوان و موضوع پروژه را وارد کن.")
        else:
            pid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + slugify(title)
            obj = {
                "id": pid, "title": title.strip(), "content_type": content_type,
                "brand": brand, "language": language, "topic": target.strip(),
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "approval_mode": True,
                "stage_status": {k: "در انتظار" for k, _ in STAGES},
                "notes": {k: "" for k, _ in STAGES},
                "approved": {k: False for k, _ in STAGES},
            }
            save_project(obj)
            st.success("پروژه ساخته شد. از نوار کناری آن را انتخاب کن.")
            st.rerun()
else:
    obj = next(p for p in projects if p["id"] == selected)
    st.subheader(obj["title"])
    c1, c2, c3 = st.columns(3)
    c1.metric("نوع محتوا", obj["content_type"])
    c2.metric("برند", obj["brand"])
    c3.metric("زبان", obj["language"])
    st.info("حالت تأیید فعال است: هر مرحله باید بررسی و تأیید شود تا مرحله بعدی نهایی شود.")

    st.markdown("### موضوع پروژه")
    st.write(obj["topic"])

    st.markdown("### مسیر تولید")
    for key, label in STAGES:
        with st.expander(label, expanded=(not obj["approved"].get(key, False))):
            status = obj["stage_status"].get(key, "در انتظار")
            st.write(f"وضعیت فعلی: **{status}**")
            note = st.text_area("متن، خروجی یا یادداشت این مرحله", value=obj["notes"].get(key, ""), key=f"note_{key}", height=130)
            a, b = st.columns([1, 3])
            with a:
                if st.button("ذخیره یادداشت", key=f"save_{key}"):
                    obj["notes"][key] = note
                    save_project(obj)
                    st.success("ذخیره شد.")
            with b:
                if obj["approved"].get(key, False):
                    if st.button("لغو تأیید این مرحله", key=f"unapprove_{key}"):
                        obj["approved"][key] = False
                        obj["stage_status"][key] = "نیازمند بازبینی"
                        save_project(obj)
                        st.rerun()
                else:
                    if st.button("تأیید این مرحله", key=f"approve_{key}"):
                        previous = [k for k, _ in STAGES if STAGES.index((k, dict(STAGES)[k])) < STAGES.index((key, dict(STAGES)[key]))]
                        if previous and not all(obj["approved"].get(p, False) for p in previous):
                            st.warning("ابتدا مرحله قبلی را تأیید کن.")
                        else:
                            obj["approved"][key] = True
                            obj["stage_status"][key] = "تأیید شد"
                            save_project(obj)
                            st.rerun()

    completed = sum(1 for k, _ in STAGES if obj["approved"].get(k, False))
    st.progress(completed / len(STAGES), text=f"پیشرفت تأیید مراحل: {completed} از {len(STAGES)}")
    st.download_button(
        "دریافت پرونده پروژه (JSON)",
        data=json.dumps(obj, ensure_ascii=False, indent=2),
        file_name=f"{obj['id']}.json",
        mime="application/json"
    )

st.divider()
st.caption("این نسخه، اسکلت اجرایی گردش‌کار و تأییدهاست. اتصال واقعی به مدل‌های متن، تولید تصویر/ویدئو، گویندگی و رندر در مراحل بعدی اضافه می‌شود؛ کلیدهای API و محدودیت اعتبار سرویس‌ها باید جداگانه تنظیم شوند.")
