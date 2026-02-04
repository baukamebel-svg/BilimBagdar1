
import streamlit as st
import json
import hashlib
import uuid
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="BilimBagdar", layout="wide")

def sha256(t):
    return hashlib.sha256(t.encode()).hexdigest()

def get_client():
    sa = json.loads(st.secrets["GCP_SERVICE_ACCOUNT"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(sa, scopes=scopes)
    return gspread.authorize(creds)

def get_sheet():
    return get_client().open_by_key(st.secrets["GSHEET_ID"])

def load_users(sh):
    try:
        ws = sh.worksheet("users")
    except:
        ws = sh.add_worksheet("users", rows=100, cols=6)
        ws.append_row(["id","role","username","password_hash","display_name","class"])
    return ws.get_all_records(), ws

sh = get_sheet()
users, users_ws = load_users(sh)

if not any(u["role"]=="teacher" for u in users):
    st.title("🔐 Алғашқы мұғалімді тіркеу")
    name = st.text_input("Аты-жөні")
    username = st.text_input("Логин")
    p1 = st.text_input("Пароль", type="password")
    p2 = st.text_input("Парольді қайталаңыз", type="password")
    if st.button("🚀 Тіркеу"):
        if p1!=p2:
            st.error("Пароль сәйкес емес")
        else:
            users_ws.append_row([str(uuid.uuid4()),"teacher",username,sha256(p1),name,""])
            st.success("Тіркелді. Бетті жаңартыңыз.")
    st.stop()

st.title("BilimBagdar – Кіру")
login = st.text_input("Логин")
password = st.text_input("Пароль", type="password")

if st.button("Кіру"):
    for u in users:
        if u["username"]==login and u["password_hash"]==sha256(password):
            st.success(f"Қош келдіңіз, {u['display_name']}!")
            st.stop()
    st.error("Қате логин немесе пароль")
