import streamlit as st
import os
import json
import io
import requests
import bcrypt
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS

# --- 1. PAGE CONFIG ---
st.set_page_config(page_title="Otak Kedua v4.0", page_icon="🧠", layout="wide")

# --- 2. SISTEM LOGIN MURNI (ANTI-BUG) ---
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.markdown("<h2 style='text-align: center;'>🔒 Login Otak Kedua</h2>", unsafe_allow_html=True)
        inp_user = st.text_input("Username")
        inp_pass = st.text_input("Password", type="password")
        
        if st.button("Masuk", use_container_width=True):
            try:
                # Cek ke secrets.toml bawaan Streamlit
                if inp_user == st.secrets["APP_USER"] and inp_pass == st.secrets["APP_PASS"]:
                    st.session_state.logged_in = True
                    st.rerun() 
                else:
                    st.error("❌ Username atau Password salah, Bre!")
            except KeyError:
                st.error("Woi Bre, tambahin APP_USER dan APP_PASS di Streamlit Secrets dulu!")
    st.stop()

# --- 3. KONFIGURASI GOOGLE DRIVE & API ---
EMAIL_UTAMA = "email_lu@gmail.com" # Ganti pake email lu

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    FOLDER_ID = st.secrets["GDRIVE_FOLDER_ID"]
    creds_info = json.loads(st.secrets["SERVICE_ACCOUNT_JSON"])
    genai.configure(api_key=API_KEY)
    os.environ["GOOGLE_API_KEY"] = API_KEY
    SCOPES = ['https://www.googleapis.com/auth/drive']
except Exception as e:
    st.error(f"Error baca Secrets: {e}")
    st.stop()

# --- 4. SESSION STATE ---
if "chats" not in st.session_state: st.session_state.chats = {"Chat Utama": []}
if "pinned_topics" not in st.session_state: st.session_state.pinned_topics = []
if "current_topic" not in st.session_state: st.session_state.current_topic = "Chat Utama"
if "file_list" not in st.session_state: st.session_state.file_list = []
if "total_tokens_in" not in st.session_state: st.session_state.total_tokens_in = 0
if "total_tokens_out" not in st.session_state: st.session_state.total_tokens_out = 0
if "kurs_idr" not in st.session_state: st.session_state.kurs_idr = 16000.0

# --- 5. BACKEND FUNCTIONS ---
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
    except: st.session_state.file_list = []

def simpan_atau_update_memori(file_selection, isi):
    try:
        service = get_drive_service()
        f_id = next(f['id'] for f in st.session_state.file_list if f['name'] == file_selection)
        old_content = service.files().export_media(fileId=f_id, mimeType='text/plain').execute().decode('utf-8')
        new_text = old_content + "\n\n---\nUpdate:\n" + isi
        media = MediaIoBaseUpload(io.BytesIO(new_text.encode('utf-8')), mimetype='text/plain', resumable=False)
        service.files().update(fileId=f_id, media_body=media, supportsAllDrives=True).execute()
        return True, "Berhasil disuntik ke G-Drive!"
    except Exception as e:
        return False, str(e)

def sync_data():
    try:
        service = get_drive_service()
        fetch_files()
        docs = []
        for f in st.session_state.file_list:
            t = service.files().export_media(fileId=f['id'], mimeType='text/plain').execute().decode('utf-8')
            docs.append(Document(page_content=t, metadata={"source": f['name']}))
        if not docs: return "error", "Folder kosong!"
        
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        chunks = splitter.split_documents(docs)
        # Pakai model embedding terbaru gemini-embedding-001
        embeddings = GoogleGenerativeAIEmbeddings(model="gemini-embedding-001", google_api_key=API_KEY)
        FAISS.from_documents(chunks, embeddings).save_local("db_ingatan_faiss")
        return "success", len(chunks)
    except Exception as e: return "error", str(e)

def cek_dan_bersihkan_sa():
    try:
        service = get_drive_service()
        about = service.about().get(fields="storageQuota").execute()
        quota = about['storageQuota']
        limit = int(quota.get('limit', 0)) / (1024**3)
        used = int(quota.get('usage', 0)) / (1024**3)
        sisa = limit - used
        if sisa < 0.1: service.files().emptyTrash().execute()
        return True, f"Sisa Kuota SA: {sisa:.2f} GB (Used: {used:.2f} GB)"
    except Exception as e: return False, str(e)

# --- 6. UI TOP BAR ---
st.title(f"🧠 {st.session_state.current_topic}")

# --- 7. UI SIDEBAR ---
with st.sidebar:
    st.markdown("<h1 style='text-align: center;'>🧠</h1>", unsafe_allow_html=True)
    if st.button("➕ Chat Baru", use_container_width=True):
        new_id = f"Chat {len(st.session_state.chats) + 1}"
        st.session_state.chats[new_id] = []
        st.session_state.current_topic = new_id
        st.rerun()
    
    st.divider()

    # MENU & BILLING (EXPANDER)
    with st.expander("⚙️ Menu & Billing", expanded=False):
        st.subheader("📊 Billing Sesi Ini")
        st.session_state.kurs_idr = fetch_realtime_kurs()
        p_in = (0.075/1e6) * st.session_state.kurs_idr
        p_out = (0.30/1e6) * st.session_state.kurs_idr
        cost = (st.session_state.total_tokens_in * p_in) + (st.session_state.total_tokens_out * p_out)
        
        c1, c2 = st.columns(2)
        c1.metric("Token In", f"{st.session_state.total_tokens_in:,}")
        c2.metric("Token Out", f"{st.session_state.total_tokens_out:,}")
        st.metric("Total Rupiah", f"Rp {cost:,.2f}")
        
        st.divider()
        st.subheader("📝 Suntik Memori")
        fetch_files()
        opts = [f['name'] for f in st.session_state.file_list]
        if opts:
            sel_file = st.selectbox("Target Catatan", opts)
            isi_memori = st.text_area("Isi Tambahan", height=100)
            if st.button("🚀 Suntik ke Drive", use_container_width=True):
                if isi_memori:
                    ok, msg = simpan_atau_update_memori(sel_file, isi_memori)
                    if ok: st.success(msg)
                    else: st.error(msg)
        
        st.divider()
        st.subheader("🛠️ Sistem")
        sel_model = st.selectbox("Model", ["gemini-2.5-flash", "gemini-2.5-pro"])
        if st.button("🔄 Sync G-Drive", use_container_width=True):
            s, m = sync_data()
            if s == "success": st.toast(f"Berhasil serap {m} data!", icon="✅")
            else: st.error(m)
        if st.button("🔍 Cek Kuota SA", use_container_width=True):
            ok, p = cek_dan_bersihkan_sa()
            st.info(p)

    st.divider()
    
    # RENDER RIWAYAT CHAT
    for t in list(st.session_state.chats.keys()):
        col1, col2 = st.columns([0.8, 0.2])
        with col1:
            if st.button(f"🗨️ {t}", key=f"t_{t}", use_container_width=True, type="primary" if t == st.session_state.current_topic else "secondary"):
                st.session_state.current_topic = t
                st.rerun()
        with col2:
            if st.button("🗑️", key=f"del_{t}"):
                if len(st.session_state.chats) > 1:
                    del st.session_state.chats[t]
                    st.session_state.current_topic = list(st.session_state.chats.keys())[0]
                    st.rerun()

    st.divider()
    if st.button("Keluar (Logout)", type="primary", use_container_width=True):
        st.session_state.logged_in = False
        st.rerun()

# --- 8. MAIN CHAT LOGIC ---
llm = ChatGoogleGenerativeAI(model=sel_model, google_api_key=API_KEY, temperature=0.3)

for m in st.session_state.chats[st.session_state.current_topic]:
    with st.chat_message(m["role"]): st.markdown(m["content"])

if p := st.chat_input("Tanya soal memori lu..."):
    st.session_state.chats[st.session_state.current_topic].append({"role": "user", "content": p})
    with st.chat_message("user"): st.markdown(p)

    with st.chat_message("assistant"):
        with st.spinner("Mencari..."):
            if not os.path.exists("db_ingatan_faiss"):
                ans = "Database kosong! Klik Sync G-Drive dulu."
            else:
                try:
                    db = FAISS.load_local("db_ingatan_faiss", GoogleGenerativeAIEmbeddings(model="gemini-embedding-001", google_api_key=API_KEY), allow_dangerous_deserialization=True)
                    res = db.similarity_search(p, k=3)
                    context = "\n\n".join([d.page_content for d in res])
                    
                    # INVOCATION
                    resp = llm.invoke(f"Konteks: {context}\n\n Pertanyaan: {p}")
                    
                    # UPDATE METERAN TOKEN
                    if hasattr(resp, 'usage_metadata') and resp.usage_metadata:
                        st.session_state.total_tokens_in += resp.usage_metadata.get('input_tokens', 0)
                        st.session_state.total_tokens_out += resp.usage_metadata.get('output_tokens', 0)
                    
                    ans = resp.content
                except Exception as e:
                    ans = f"Error: {e}"
        
        st.markdown(ans)
        st.session_state.chats[st.session_state.current_topic].append({"role": "assistant", "content": ans})
        st.rerun()