import io
import json
import uuid
import base64
import hashlib
from datetime import datetime, date

import pandas as pd
import streamlit as st

# ------------------ GOOGLE SHEETS / DRIVE ------------------
# Uses a Google Service Account.
# In Streamlit Cloud → App → Settings → Secrets, add:
# GCP_SERVICE_ACCOUNT = "{...service account json...}"
# GSHEET_ID = "your_sheet_id"
# DRIVE_FOLDER_ID = "your_drive_folder_id"   (optional, for file uploads)
#
# Also share the Google Sheet and the Drive folder with the service account email.

def get_gcp_sa():
    if hasattr(st, "secrets") and "GCP_SERVICE_ACCOUNT" in st.secrets:
        return json.loads(st.secrets["GCP_SERVICE_ACCOUNT"])
    return None

def get_gsheet_id():
    if hasattr(st, "secrets") and "GSHEET_ID" in st.secrets:
        return st.secrets["GSHEET_ID"]
    return None

def get_drive_folder_id():
    if hasattr(st, "secrets") and "DRIVE_FOLDER_ID" in st.secrets:
        return st.secrets["DRIVE_FOLDER_ID"]
    return None

@st.cache_resource
def gspread_client():
    sa = get_gcp_sa()
    if not sa:
        return None
    import gspread
    return gspread.service_account_from_dict(sa)

def ensure_worksheets(sh):
    wanted = {
        "homework": ["id","class","date","topic","task_text","expected_answer","step_hints","created_at"],
        "submissions": ["id","submitted_at","student_name","student_username","class","date","hw_id","topic","task_text","work_text","final_answer","attachments_json","ai_reflection","needs_review_json","next_steps_json","correct","flags_json"],
        "users": ["id","role","username","password_hash","display_name","class"],
    }
    for title, headers in wanted.items():
        try:
            ws = sh.worksheet(title)
        except Exception:
            ws = sh.add_worksheet(title=title, rows=1000, cols=max(10, len(headers)+2))
            ws.append_row(headers)
        existing = ws.row_values(1)
        if not existing or existing != headers:
            ws.clear()
            ws.append_row(headers)

def sheet_read_all(ws):
    return ws.get_all_records()

def sheet_append(ws, row_dict, headers):
    row = [row_dict.get(h,"") for h in headers]
    ws.append_row(row)

def sheet_update_row_by_id(ws, headers, row_id, updates: dict):
    col = ws.col_values(1)
    try:
        idx = col.index(row_id) + 1
    except ValueError:
        return False
    current = ws.row_values(idx)
    data = {headers[i]: (current[i] if i < len(current) else "") for i in range(len(headers))}
    data.update(updates)
    new_row = [data.get(h,"") for h in headers]
    ws.update(f"A{idx}:{chr(65+len(headers)-1)}{idx}", [new_row])
    return True

# ------------------ Google Drive upload (optional) ------------------
@st.cache_resource
def drive_service():
    sa = get_gcp_sa()
    folder = get_drive_folder_id()
    if not sa or not folder:
        return None
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
        scopes = ["https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(sa, scopes=scopes)
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception:
        return None

def drive_upload(file, folder_id: str):
    svc = drive_service()
    if not svc:
        return None
    from googleapiclient.http import MediaIoBaseUpload
    fh = io.BytesIO(file.getvalue())
    media = MediaIoBaseUpload(fh, mimetype=file.type, resumable=False)
    metadata = {"name": file.name, "parents":[folder_id]}
    created = svc.files().create(body=metadata, media_body=media, fields="id, webViewLink").execute()
    # Public link (anyone with link). Comment out if you want private.
    try:
        svc.permissions().create(fileId=created["id"], body={"type":"anyone","role":"reader"}).execute()
    except Exception:
        pass
    link = created.get("webViewLink") or f"https://drive.google.com/file/d/{created['id']}/view"
    return {"name": file.name, "type": file.type, "drive_file_id": created["id"], "url": link, "size": file.size}

# ------------------ Auth helpers ------------------
def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def require_login(role=None):
    u = st.session_state.get("user")
    if not u:
        return False
    if role and u.get("role") != role:
        return False
    return True

# ------------------ Optional: OpenAI ------------------
def get_openai_client():
    try:
        from openai import OpenAI
        key = None
        if hasattr(st, "secrets") and "OPENAI_API_KEY" in st.secrets:
            key = st.secrets["OPENAI_API_KEY"]
        if not key:
            import os
            key = os.getenv("OPENAI_API_KEY")
        if not key:
            return None
        return OpenAI(api_key=key)
    except Exception:
        return None

def smart_hints_reply(hw: dict, user_q: str) -> str:
    hints = (hw.get("step_hints") or "").strip()
    topic = (hw.get("topic") or "").strip()
    task = (hw.get("task_text") or "").strip()
    uq = user_q.lower()

    if any(k in uq for k in ["қадам", "қалай", "бастау", "көмек", "start"]):
        if hints:
            return f"Бастау үшін мына қадамдарды ұстан:\n\n{hints}\n\nҚай қадамда тоқтап қалдың? (1,2,3...) деп жаз."
        return f"Тақырып: **{topic}**.\nТапсырма: {task}\n\n1) Берілгенді жаз.\n2) Формуланы/ережеңді таңда.\n3) Есептеуді жүргіз.\n4) Жауабыңды тексер.\n\nҚай жері түсініксіз?"
    if any(k in uq for k in ["жауап", "дұрыс", "тексер", "correct"]):
        return "Жауапты тексеру үшін шешу жолыңды 1–2 қадаммен көрсет. Мен қателікті тауып, түзетуге бағыт берем."
    if hints:
        return f"Мына қадамдарға сүйен:\n\n{hints}\n\nӨзің шығарған алғашқы 1-2 қадамды жібер."
    return "Алғашқы 1-2 қадамыңды жазып жібер: берілгені, қандай формула/ереже таңдадың?"

def openai_reply(client, hw: dict, messages: list[dict]) -> str:
    system = (
        "You are a helpful math tutor for school students. "
        "Coach step-by-step. Do not dump full solutions. "
        "Respond in Kazakh. Ask for the student's attempt before giving strong hints."
    )
    context = (
        f"Homework topic: {hw.get('topic','')}\n"
        f"Task: {hw.get('task_text','')}\n"
        f"Teacher step hints: {hw.get('step_hints','')}\n"
    )
    final_messages = [{"role":"system","content": system + "\n\n" + context}] + messages
    try:
        resp = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=final_messages,
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return smart_hints_reply(hw, messages[-1]["content"])

def build_reflection(hw: dict, student_answer: str, chat: list[dict]) -> dict:
    expected = (hw.get("expected_answer") or "").strip()
    topic = (hw.get("topic") or "").strip()

    correct = None
    if expected:
        correct = (student_answer.strip() == expected)

    flags = []
    if len(chat) >= 8:
        flags.append("Көп сұрақ қойылды → кей қадам түсініксіз болуы мүмкін.")
    if any(m.get("role")=="user" and any(k in m.get("content","").lower() for k in ["түсінбедім","қиын","шатастым","қате"]) for m in chat):
        flags.append("Оқушы қиындықты атап өтті (түсінбедім/қиын/қате).")

    client = get_openai_client()
    if client:
        msgs = [{"role":"user","content":
                 "Оқушы жұмысы бойынша қысқа рефлексия жаса.\n"
                 f"Тақырып: {topic}\n"
                 f"Оқушының соңғы жауабы: {student_answer}\n"
                 f"Дұрыс жауап (егер бар болса): {expected or 'берілмеген'}\n"
                 f"Чат үзіндісі: {[(m['role'], m['content'][:120]) for m in chat][-10:]}\n\n"
                 "Шығыс: (1) 3-5 сөйлем рефлексия (2) Қай дағды/тақырыпты қайталау керек (3) Келесі қадам (2 пункт)."
                }]
        txt = openai_reply(client, hw, msgs)
        return {"reflection_text": txt, "needs_review": [], "next_steps": [], "correct": correct, "flags": flags}

    needs = []
    if topic:
        needs.append(topic)
    if "теңдеу" in topic.lower():
        needs += ["Теңдеуді түрлендіру", "Тексеру (орнына қою)"]
    if "процент" in topic.lower():
        needs += ["Процент ↔ бөлшек/ондық", "Арзандату/қымбаттау типтері"]
    if "үшбұрыш" in topic.lower() or "геометр" in topic.lower():
        needs += ["Бұрыштардың қосындысы", "Дәлелдеу тілі"]
    needs = list(dict.fromkeys([n for n in needs if n]))

    parts = ["Рефлексия:"]
    parts.append("- Сен тапсырманы қадамдап орындауға тырыстың.")
    if expected:
        parts.append("- Жауабың " + ("дұрыс ✅" if correct else "дұрыс емес ❗") + ". Қай қадамда қате кеткенін тексер.")
    else:
        parts.append("- Жауапты тексеру үшін есептеулерді және соңғы тексеруді қайта қарап шық.")
    if flags:
        parts.append("- Байқалған қиындық: " + " ".join(flags))

    next_steps = [
        "Шешу жолын 3–4 қысқа қадаммен қайта жаз (берілгені → ереже/формула → есептеу → тексеру).",
        "Қиын болған қадамды атап жаз: «Мен ... жерде қиналдым» — сол жерден бастап түзетеміз."
    ]
    return {"reflection_text":"\n".join(parts), "needs_review": needs, "next_steps": next_steps, "correct": correct, "flags": flags}

HEADERS = {
    "homework": ["id","class","date","topic","task_text","expected_answer","step_hints","created_at"],
    "submissions": ["id","submitted_at","student_name","student_username","class","date","hw_id","topic","task_text","work_text","final_answer","attachments_json","ai_reflection","needs_review_json","next_steps_json","correct","flags_json"],
    "users": ["id","role","username","password_hash","display_name","class"],
}

def load_all():
    gc = gspread_client()
    gsid = get_gsheet_id()
    if gc and gsid:
        sh = gc.open_by_key(gsid)
        ensure_worksheets(sh)
        return (
            sheet_read_all(sh.worksheet("homework")),
            sheet_read_all(sh.worksheet("submissions")),
            sheet_read_all(sh.worksheet("users")),
            ("gsheets", sh)
        )
    # local fallback
    def _load_local(path, default):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return (
        _load_local("homework.json", []),
        _load_local("submissions.json", []),
        _load_local("users.json", []),
        ("local", None)
    )

def save_homework(hw_item, backend):
    mode, sh = backend
    if mode == "gsheets":
        sheet_append(sh.worksheet("homework"), hw_item, HEADERS["homework"])
    else:
        data = _load_local("homework.json", [])
        data.append(hw_item)
        _save_local("homework.json", data)

def save_submission(sub_item, backend):
    mode, sh = backend
    sub_item = sub_item.copy()
    sub_item["attachments_json"] = json.dumps(sub_item.get("attachments", []), ensure_ascii=False)
    sub_item["needs_review_json"] = json.dumps(sub_item.get("needs_review", []), ensure_ascii=False)
    sub_item["next_steps_json"] = json.dumps(sub_item.get("next_steps", []), ensure_ascii=False)
    sub_item["flags_json"] = json.dumps(sub_item.get("flags", []), ensure_ascii=False)
    for k in ["attachments","needs_review","next_steps","flags"]:
        sub_item.pop(k, None)

    if mode == "gsheets":
        sheet_append(sh.worksheet("submissions"), sub_item, HEADERS["submissions"])
    else:
        data = _load_local("submissions.json", [])
        data.append(sub_item)
        _save_local("submissions.json", data)

def upsert_user(user_item, backend, user_id=None):
    mode, sh = backend
    if mode == "gsheets":
        ws = sh.worksheet("users")
        if user_id:
            sheet_update_row_by_id(ws, HEADERS["users"], user_id, user_item)
        else:
            sheet_append(ws, user_item, HEADERS["users"])
    else:
        data = _load_local("users.json", [])
        if user_id:
            for i,u in enumerate(data):
                if u.get("id")==user_id:
                    data[i].update(user_item)
                    break
        else:
            data.append(user_item)
        _save_local("users.json", data)

def _load_local(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _save_local(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

# ------------------ App UI ------------------
st.title("🧠 BilimBagdar v3 — Google Sheets")
st.caption("Тұрақты сақтау: Google Sheets. Файл үшін: Google Drive ұсынылады.")

homework, subs_raw, users, backend = load_all()

# ------------------ BOOTSTRAP: first teacher registration ------------------
def has_teacher(users_list):
    return any(u.get("role") == "teacher" for u in users_list)

def bootstrap_first_teacher(users_list, backend):
    st.warning("Бұл жүйеде әзірге мұғалім аккаунты жоқ. Алғашқы мұғалімді тіркеңіз (1 рет).")
    name = st.text_input("Мұғалім аты-жөні", placeholder="Мысалы: Перизат Жақсылықова")
    username = st.text_input("Логин", placeholder="мыс: perizat71")
    password = st.text_input("Пароль", type="password")
    password2 = st.text_input("Парольді қайталаңыз", type="password")

    colA, colB = st.columns(2)
    with colA:
        st.info("✅ Тіркелген соң жүйеге бірден кіресіз.")
    with colB:
        st.info("🔒 Пароль hash түрінде сақталады.")

    if st.button("🚀 Мұғалімді тіркеу", use_container_width=True):
        if not (name.strip() and username.strip() and password):
            st.error("Барлық өрісті толтырыңыз.")
            st.stop()
        if password != password2:
            st.error("Парольдер сәйкес емес.")
            st.stop()
        if any(u.get("username","").lower().strip() == username.lower().strip() for u in users_list):
            st.error("Бұл логин бос емес.")
            st.stop()

        user_item = {
            "id": "u-teacher-" + str(uuid.uuid4()),
            "role": "teacher",
            "username": username.strip(),
            "password_hash": sha256(password),
            "display_name": name.strip(),
            "class": ""
        }
        upsert_user(user_item, backend)
        st.success("Мұғалім аккаунты құрылды ✅ Енді логинмен кіре аласыз.")
        st.session_state.user = user_item
        st.session_state.chat = {}
        st.rerun()



# Normalize submissions
subs=[]
for s in subs_raw:
    s=dict(s)
    for k in ["attachments_json","needs_review_json","next_steps_json","flags_json"]:
        s.setdefault(k, "[]")
    for k, dst in [("attachments_json","attachments"),("needs_review_json","needs_review"),("next_steps_json","next_steps"),("flags_json","flags")]:
        try:
            s[dst]=json.loads(s.get(k) or "[]")
        except Exception:
            s[dst]=[]
    subs.append(s)

mode, _ = backend
st.write(f"**Сақтау режимі:** {'Google Sheets ✅' if mode=='gsheets' else 'Локал JSON (fallback)'}")

# login bar
if st.session_state.get("user"):
    st.success(f"Кірген: {st.session_state['user'].get('display_name')} ({st.session_state['user'].get('role')})")
    if st.button("🚪 Шығу"):
        st.session_state.user=None
        st.session_state.chat={}
        st.rerun()

tabs = st.tabs(["🔐 Кіру", "👨‍🎓 Оқушы", "👩‍🏫 Мұғалім", "📊 Аналитика", "👥 Оқушылар"])

with tabs[0]:
    st.subheader("Кіру")
    username = st.text_input("Логин")
    password = st.text_input("Пароль", type="password")
    if st.button("Кіру", use_container_width=True):
        user=None
        for u in users:
            if u.get("username","").lower().strip()==username.lower().strip():
                user=u; break
        if not user:
            st.error("Логин табылмады.")
        elif user.get("password_hash")!=sha256(password):
            st.error("Пароль қате.")
        else:
            st.session_state.user=user
            st.success("Кіру сәтті ✅")
            st.rerun()

with tabs[1]:
    st.subheader("Оқушы")
    if not require_login("student"):
        st.info("Оқушы болып кіріңіз.")
    else:
        user=st.session_state["user"]
        s_name=user.get("display_name")
        s_class=user.get("class")
        st.write(f"**Оқушы:** {s_name} | **Сынып:** {s_class}")

        s_date = st.date_input("Күні", value=date.today())
        todays=[h for h in homework if h.get("class")==s_class and h.get("date")==s_date.isoformat()]
        if not todays:
            st.info("Бұл күнге үй тапсырмасы жоқ.")
        else:
            hw=st.selectbox("Үй тапсырмасы", todays, format_func=lambda x: f"{x.get('topic')} | {x.get('date')}")
            st.info(hw.get("task_text",""))

            work_text=st.text_area("Шешу жолы (міндетті)", height=140)
            uploaded=st.file_uploader("Фото/файл (Drive қосылса сілтеме сақталады)", accept_multiple_files=True)

            if "chat" not in st.session_state:
                st.session_state.chat={}
            chat_key=hw["id"]
            st.session_state.chat.setdefault(chat_key, [])

            for m in st.session_state.chat[chat_key]:
                with st.chat_message(m["role"]):
                    st.write(m["content"])

            q=st.chat_input("Сұрағыңды жаз...")
            if q:
                st.session_state.chat[chat_key].append({"role":"user","content":q})
                client=get_openai_client()
                reply=openai_reply(client, hw, st.session_state.chat[chat_key]) if client else smart_hints_reply(hw,q)
                st.session_state.chat[chat_key].append({"role":"assistant","content":reply})
                st.rerun()

            final_answer=st.text_input("Соңғы жауап")

            if st.button("📩 Жіберу", use_container_width=True):
                if not work_text.strip():
                    st.error("Шешу жолын жазыңыз.")
                    st.stop()
                attachments=[]
                folder_id=get_drive_folder_id()
                if uploaded:
                    for f in uploaded:
                        if folder_id and drive_service():
                            up=drive_upload(f, folder_id)
                            if up: attachments.append(up)
                        else:
                            # fallback base64 (avoid big files)
                            b64=base64.b64encode(f.getvalue()).decode("ascii")
                            attachments.append({"name":f.name,"type":f.type,"data_b64":b64,"size":f.size})

                chat=st.session_state.chat[chat_key]
                ref=build_reflection(hw, final_answer, chat)

                sub_item={
                    "id": str(uuid.uuid4()),
                    "submitted_at": now_iso(),
                    "student_name": s_name,
                    "student_username": user.get("username"),
                    "class": s_class,
                    "date": hw.get("date"),
                    "hw_id": hw.get("id"),
                    "topic": hw.get("topic"),
                    "task_text": hw.get("task_text"),
                    "work_text": work_text.strip(),
                    "final_answer": final_answer.strip(),
                    "attachments": attachments,
                    "ai_reflection": ref.get("reflection_text",""),
                    "needs_review": ref.get("needs_review", []),
                    "next_steps": ref.get("next_steps", []),
                    "correct": ref.get("correct", None),
                    "flags": ref.get("flags", []),
                }
                save_submission(sub_item, backend)
                st.success("Сақталды ✅ (Sheets)")

with tabs[2]:
    st.subheader("Мұғалім")
    if not require_login("teacher"):
        st.info("Мұғалім болып кіріңіз.")
    else:
        colA,colB,colC=st.columns(3)
        with colA: hw_class=st.selectbox("Сынып", ["5","6","7","8","9","10","11"])
        with colB: hw_date=st.date_input("Күні", value=date.today())
        with colC: hw_topic=st.text_input("Тақырып")
        task_text=st.text_area("Тапсырма мәтіні", height=120)
        exp=st.text_input("Күтілетін жауап (қалау бойынша)")
        hints=st.text_area("Қадамдық бағыт (AI)", height=120)

        if st.button("➕ Үй тапсырмасын сақтау", use_container_width=True):
            if not hw_topic.strip() or not task_text.strip():
                st.error("Тақырып пен тапсырма мәтіні керек.")
            else:
                hw_item={
                    "id": str(uuid.uuid4()),
                    "class": hw_class,
                    "date": hw_date.isoformat(),
                    "topic": hw_topic.strip(),
                    "task_text": task_text.strip(),
                    "expected_answer": exp.strip(),
                    "step_hints": hints.strip(),
                    "created_at": now_iso()
                }
                save_homework(hw_item, backend)
                st.success("Сақталды ✅")
                st.rerun()

        st.divider()
        st.markdown("### Оқушы жұмыстарын көру")
        if not subs:
            st.warning("Жұмыс жоқ.")
        else:
            for s in reversed(subs):
                with st.expander(f"{s['submitted_at']} | {s['class']} | {s['student_name']} | {s['topic']}"):
                    st.write(s["task_text"])
                    st.code(s.get("work_text",""))
                    st.write("Жауап:", s.get("final_answer","—"))
                    if s.get("attachments"):
                        st.write("Файлдар:")
                        for a in s["attachments"]:
                            if "url" in a:
                                st.markdown(f"- [{a['name']}]({a['url']})")
                            else:
                                st.write(f"- {a.get('name')} (base64)")

                    st.write("AI рефлексия:")
                    st.write(s.get("ai_reflection","—"))

with tabs[3]:
    st.subheader("Аналитика")
    if not require_login("teacher"):
        st.info("Мұғалім болып кіріңіз.")
    else:
        if not subs:
            st.warning("Дерек жоқ.")
        else:
            df=pd.DataFrame(subs)
            by_topic=df.groupby("topic").agg(works=("id","count")).reset_index().sort_values("works", ascending=False)
            st.dataframe(by_topic, use_container_width=True, hide_index=True)
            st.bar_chart(by_topic.set_index("topic")[["works"]])

            flat=[]
            for lst in df["needs_review"].tolist():
                if isinstance(lst, list): flat += lst
            if flat:
                import pandas as pd
                top=pd.Series(flat).value_counts().head(15)
                st.bar_chart(top)

with tabs[4]:
    st.subheader("Оқушылар")
    if not require_login("teacher"):
        st.info("Мұғалім болып кіріңіз.")
    else:
        name=st.text_input("Аты-жөні")
        cl=st.selectbox("Сынып", ["5","6","7","8","9","10","11"], key="cl_new")
        un=st.text_input("Логин", key="un_new")
        pw=st.text_input("Пароль", type="password", key="pw_new")
        if st.button("➕ Оқушы қосу", use_container_width=True):
            if not (name.strip() and un.strip() and pw):
                st.error("Барлығын толтырыңыз.")
            elif any(u.get("username","").lower()==un.lower().strip() for u in users):
                st.error("Логин бос емес.")
            else:
                user_item={
                    "id": "u-" + str(uuid.uuid4()),
                    "role":"student",
                    "username": un.strip(),
                    "password_hash": sha256(pw),
                    "display_name": name.strip(),
                    "class": cl
                }
                upsert_user(user_item, backend)
                st.success("Оқушы қосылды ✅")
                st.rerun()

        students=[u for u in users if u.get("role")=="student"]
        if students:
            st.dataframe(pd.DataFrame([{"аты":u["display_name"],"сынып":u["class"],"логин":u["username"]} for u in students]),
                         use_container_width=True, hide_index=True)
