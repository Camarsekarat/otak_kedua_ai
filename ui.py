import streamlit as st
import os
import json
import io
import requests
import datetime
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS

# --- 1. PAGE CONFIG & PREMIUM UI ---
st.set_page_config(page_title="Otak Kedua v5.3", page_icon="🧠", layout="wide")

st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {background-color: transparent !important;}
    [data-testid="stHeader"] {background-color: transparent !important;}
    
    .block-container {
        max-width: 800px !important;
        padding-top: 1rem !important;
    }

    [data-testid="stChatMessage"]:has([alt="user avatar"]) {
        background-color: #1e1f22; 
        border-radius: 20px 20px 5px 20px;
        padding: 12px 18px;
        margin-bottom: 20px;
        border: 1px solid #2d3036;
    }

    [data-testid="stChatMessage"]:has([alt="assistant avatar"]) {
        background-color: transparent;
        padding: 10px 0;
        margin-bottom: 20px;
    }

    [data-testid="stSidebar"] {
        background-color: #131314 !important;
        border-right: 1px solid #282a2c !important;
    }
    
    /* Tombol Secondary (Regenerate, Copy, History) -> DIBIKIN TELANJANG (Minimalis) */
    .stButton > button[kind="secondary"], div[data-testid="stPopover"] > button {
        background-color: transparent !important;
        border: none !important;
        color: #9aa0a6 !important;
        padding: 0 !important;
        min-height: auto !important;
        height: auto !important;
        font-size: 14px !important;
        box-shadow: none !important;
        justify-content: flex-start !important;
    }
    .stButton > button[kind="secondary"]:hover, div[data-testid="stPopover"] > button:hover {
        color: #ffffff !important;
        background-color: transparent !important;
    }

    /* Tombol Primary (Action Utama) -> Tetep ada bentuknya tapi elegan */
    .stButton > button[kind="primary"] {
        background-color: #2b313e !important;
        border: 1px solid #3c4456 !important;
        border-radius: 6px !important;
        color: #d1d5db !important;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: #3b4252 !important;
        border-color: #4c566a !important;
        color: white !important;
    }
</style>
""", unsafe_allow_html=True)

# --- 2. KONFIGURASI API ---
try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    FOLDER_ID = st.secrets["GDRIVE_FOLDER_ID"]
    creds_info = json.loads(st.secrets["SERVICE_ACCOUNT_JSON"])
    genai.configure(api_key=API_KEY)
    os.environ["GOOGLE_API_KEY"] = API_KEY
    SCOPES = ['https://www.googleapis.com/auth/drive']
except Exception as e:
    st.error(f"Error Secrets: {e}")
    st.stop()

# --- 3. DATABASE LOKAL & SESSION STATE ---
DB_FILE = "app_database.json"

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return {"chats": {"Chat Utama": []}, "billing": {}}

def save_db():
    data = {"chats": st.session_state.chats, "billing": st.session_state.billing}
    with open(DB_FILE, "w") as f:
        json.dump(data, f)

db_data = load_db()
if "chats" not in st.session_state: st.session_state.chats = db_data["chats"]
if "billing" not in st.session_state: st.session_state.billing = db_data["billing"]
if "current_topic" not in st.session_state: st.session_state.current_topic = list(st.session_state.chats.keys())[0]
if "file_list" not in st.session_state: st.session_state.file_list = []

# --- 4. BACKEND FUNCTIONS ---
@st.cache_data(ttl=3600)
def fetch_realtime_kurs():
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD")
        return float(r.json()["rates"]["IDR"])
    except: return 16000.0

def get_drive_service():
    creds = service_account.Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def fetch_files():
    try:
        service = get_drive_service()
        q = f"'{FOLDER_ID}' in parents and trashed=false and mimeType='application/vnd.google-apps.document'"
        results = service.files().list(q=q, fields="files(id, name)").execute()
        st.session_state.file_list = results.get('files', [])
    except: pass

def sync_data():
    service = get_drive_service()
    fetch_files()
    docs = []
    for f in st.session_state.file_list:
        t = service.files().export_media(fileId=f['id'], mimeType='text/plain').execute().decode('utf-8')
        docs.append(Document(page_content=t, metadata={"source": f['name']}))
    if docs:
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        chunks = splitter.split_documents(docs)
        embeddings = GoogleGenerativeAIEmbeddings(model="gemini-embedding-001", google_api_key=API_KEY)
        FAISS.from_documents(chunks, embeddings).save_local("db_ingatan_faiss")

def simpan_atau_update_memori(file_selection, isi):
    try:
        service = get_drive_service()
        f_id = next(f['id'] for f in st.session_state.file_list if f['name'] == file_selection)
        old_content = service.files().export_media(fileId=f_id, mimeType='text/plain').execute().decode('utf-8')
        new_text = old_content + "\n\n---\nUpdate:\n" + isi
        media = MediaIoBaseUpload(io.BytesIO(new_text.encode('utf-8')), mimetype='text/plain', resumable=False)
        service.files().update(fileId=f_id, media_body=media, supportsAllDrives=True).execute()
        sync_data()
        return True, "Berhasil disuntik!"
    except Exception as e: return False, str(e)

def hitung_biaya(tokens_in, tokens_out):
    kurs = fetch_realtime_kurs()
    return (tokens_in * ((0.075/1e6)*kurs)) + (tokens_out * ((0.30/1e6)*kurs))

# --- 5. SISTEM LOGIN ---
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.markdown("<h2 style='text-align: center;'>🔒 Login</h2>", unsafe_allow_html=True)
        inp_user = st.text_input("Username")
        inp_pass = st.text_input("Password", type="password")
        if st.button("Masuk", type="primary", use_container_width=True):
            if inp_user == st.secrets.get("APP_USER") and inp_pass == st.secrets.get("APP_PASS"):
                st.session_state.logged_in = True
                if not os.path.exists("db_ingatan_faiss"):
                    with st.spinner("Sync awal..."): sync_data()
                st.rerun() 
            else: st.error("❌ Salah, Bre!")
    st.stop()

# --- 6. UI SIDEBAR ---
with st.sidebar:
    st.markdown("<h1 style='text-align: center;'>🧠</h1>", unsafe_allow_html=True)
    if st.button("➕ Chat Baru", type="primary", use_container_width=True):
        new_id = f"Chat {len(st.session_state.chats) + 1}"
        st.session_state.chats[new_id] = []
        st.session_state.current_topic = new_id
        save_db()
        st.rerun()
    st.divider()

    with st.expander("📝 Suntik Memori", expanded=False):
        fetch_files()
        opts = [f['name'] for f in st.session_state.file_list]
        if opts:
            sel_file = st.selectbox("Target", opts)
            isi_memori = st.text_area("Isi Tambahan", height=100)
            if st.button("🚀 Suntik & Sync", type="primary", use_container_width=True):
                with st.spinner("Menyuntik..."):
                    ok, msg = simpan_atau_update_memori(sel_file, isi_memori)
                    if ok: st.success(msg)
                    else: st.error(msg)
        st.divider()
        if st.button("💾 Backup DB", type="primary", use_container_width=True):
            with st.spinner("Backup..."):
                try:
                    with open(DB_FILE, "r") as f: db_content = f.read()
                    service = get_drive_service()
                    q = f"'{FOLDER_ID}' in parents and name='backup_otak_kedua.json' and trashed=false"
                    files = service.files().list(q=q, fields="files(id)").execute().get('files', [])
                    media = MediaIoBaseUpload(io.BytesIO(db_content.encode('utf-8')), mimetype='application/json', resumable=False)
                    if files: service.files().update(fileId=files[0]['id'], media_body=media).execute()
                    else: service.files().create(body={'name': 'backup_otak_kedua.json', 'parents': [FOLDER_ID]}, media_body=media).execute()
                    st.success("✅ Aman!")
                except: st.error("Gagal backup")

    with st.expander("📊 Billing", expanded=False):
        t_str = datetime.date.today().isoformat()
        t_in = st.session_state.billing.get(t_str, {}).get("in", 0)
        t_out = st.session_state.billing.get(t_str, {}).get("out", 0)
        st.metric("Hari Ini", f"Rp {hitung_biaya(t_in, t_out):,.2f}")

    st.divider()
    st.markdown("### Riwayat Chat")
    for t in list(st.session_state.chats.keys()):
        c1, c2 = st.columns([0.8, 0.2])
        with c1:
            # History jadi secondary biar "telanjang" & minimalis
            if st.button(f"🗨️ {t}", key=f"t_{t}", type="secondary", use_container_width=True):
                st.session_state.current_topic = t
                st.rerun()
        with c2:
            if st.button("🗑️", key=f"del_{t}", type="secondary"):
                if len(st.session_state.chats) > 1:
                    del st.session_state.chats[t]
                    st.session_state.current_topic = list(st.session_state.chats.keys())[0]
                    save_db()
                    st.rerun()

# --- 7. MAIN CHAT LOGIC ---
st.title(f"🧠 {st.session_state.current_topic}")

# Render Riwayat Obrolan
for m in st.session_state.chats[st.session_state.current_topic]:
    with st.chat_message(m["role"], avatar="🧑‍💻" if m["role"] == "user" else "✨"): 
        st.markdown(m["content"])
        if "sumber" in m and m["sumber"]:
            with st.expander("🔍 Intip Sumber Data"): st.markdown(m["sumber"])

# --- TOMBOL MINIMALIS DI BAWAH CHAT TERAKHIR ---
chat_history = st.session_state.chats[st.session_state.current_topic]
regen_trigger = False

if len(chat_history) > 0 and chat_history[-1]["role"] == "assistant":
    col1, col2, col3 = st.columns([0.15, 0.15, 0.7])
    with col1:
        # Pake type="secondary" biar dapet CSS telanjang
        if st.button("🔄 Regenerate", type="secondary", use_container_width=True):
            regen_trigger = True
    with col2:
        with st.popover("📋 Salin", use_container_width=True):
            st.caption("Klik logo copy di bawah 👇")
            st.code(chat_history[-1]["content"], language="markdown")

# --- PINDAHIN MODEL AI KE DEKET INPUT CHAT ---
st.write("") # Spasi dikit
c_kosong, c_model = st.columns([0.8, 0.2])
with c_model:
    sel_model = st.selectbox("Model", ["gemini-2.5-flash", "gemini-2.5-pro"], label_visibility="collapsed")

# Tangkap Input User
p = st.chat_input("Tanya soal isi memori lu...")
llm = ChatGoogleGenerativeAI(model=sel_model, google_api_key=API_KEY, temperature=0.3)

if p or regen_trigger:
    if regen_trigger:
        st.session_state.chats[st.session_state.current_topic].pop()
        p = st.session_state.chats[st.session_state.current_topic][-1]["content"]
        st.session_state.chats[st.session_state.current_topic].pop()

    st.session_state.chats[st.session_state.current_topic].append({"role": "user", "content": p})
    with st.chat_message("user", avatar="🧑‍💻"): st.markdown(p)
    save_db()

    with st.chat_message("assistant", avatar="✨"):
        if not os.path.exists("db_ingatan_faiss"):
            st.error("Suntik data dulu di Menu Samping.")
        else:
            try:
                db = FAISS.load_local("db_ingatan_faiss", GoogleGenerativeAIEmbeddings(model="gemini-embedding-001", google_api_key=API_KEY), allow_dangerous_deserialization=True)
                res = db.similarity_search(p, k=3)
                
                teks_sumber = "**Data yang dibaca AI:**\n\n"
                for doc in res: teks_sumber += f"📄 **{doc.metadata.get('source')}**\n> ...{doc.page_content[-150:]}\n\n"
                context_gabungan = "\n\n---\n\n".join([d.page_content for d in res])
                
                prompt_final = f"Lu asisten Otak Kedua. 1. Jawab pakai KONTEKS G-DRIVE. 2. JIKA DI KONTEKS G-DRIVE TIDAK ADA, LU BOLEH JAWAB pake pengetahuan umum tapi awali dengan 'Di ingatan G-Drive belum ada Bre, tapi menurut gue...'\n\nKONTEKS: {context_gabungan}\n\nPERTANYAAN: {p}"
                
                with st.expander("🔍 Intip Sumber Data"): st.markdown(teks_sumber)

                response_placeholder = st.empty()
                full_answer = ""
                for chunk in llm.stream(prompt_final):
                    full_answer += chunk.content
                    response_placeholder.markdown(full_answer + " ▌") 
                response_placeholder.markdown(full_answer)
                
                st.session_state.chats[st.session_state.current_topic].append({"role": "assistant", "content": full_answer, "sumber": teks_sumber})
                
                t_str = datetime.date.today().isoformat()
                if t_str not in st.session_state.billing: st.session_state.billing[t_str] = {"in": 0, "out": 0}
                st.session_state.billing[t_str]["in"] += len(prompt_final.split()) * 1.3
                st.session_state.billing[t_str]["out"] += len(full_answer.split()) * 1.3
                save_db() 
                st.rerun()

            except Exception as e: st.error(f"Error AI: {e}")