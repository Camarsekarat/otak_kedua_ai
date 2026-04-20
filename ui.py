import streamlit as st
import os
import json
import io
import requests
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS

# --- 1. CONFIG & SECRETS ---
st.set_page_config(page_title="Otak Kedua v3.4", page_icon="🧠", layout="wide")

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    FOLDER_ID = st.secrets["GDRIVE_FOLDER_ID"]
    creds_info = json.loads(st.secrets["SERVICE_ACCOUNT_JSON"])
    genai.configure(api_key=API_KEY)
    os.environ["GOOGLE_API_KEY"] = API_KEY
    SCOPES = ['https://www.googleapis.com/auth/drive']
except:
    st.error("Secrets bermasalah, Bre!")
    st.stop()

# --- 2. SESSION STATE ---
if "chats" not in st.session_state:
    st.session_state.chats = {"Utama": []}
if "pinned_topics" not in st.session_state:
    st.session_state.pinned_topics = [] # Simpan list nama topik yang di-pin
if "current_topic" not in st.session_state:
    st.session_state.current_topic = "Utama"
if "file_list" not in st.session_state:
    st.session_state.file_list = []
if "total_tokens_in" not in st.session_state:
    st.session_state.total_tokens_in = 0
if "total_tokens_out" not in st.session_state:
    st.session_state.total_tokens_out = 0
if "kurs_idr" not in st.session_state:
    st.session_state.kurs_idr = 16000.0

# --- 3. BACKEND FUNCTIONS ---

@st.cache_data(ttl=3600)
def fetch_realtime_kurs():
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD")
        return float(r.json()["rates"]["IDR"])
    except: return 16000.0

def get_cost_estimate():
    st.session_state.kurs_idr = fetch_realtime_kurs()
    total_usd = (st.session_state.total_tokens_in * (0.075/1e6)) + (st.session_state.total_tokens_out * (0.30/1e6))
    return total_usd * st.session_state.kurs_idr

def get_drive_service():
    creds = service_account.Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def fetch_files():
    try:
        service = get_drive_service()
        q = f"'{FOLDER_ID}' in parents and trashed=false and mimeType='application/vnd.google-apps.document'"
        st.session_state.file_list = service.files().list(q=q, fields="files(id, name)").execute().get('files', [])
    except: st.session_state.file_list = []

def sync_data():
    try:
        service = get_drive_service()
        fetch_files()
        docs = []
        for f in st.session_state.file_list:
            t = service.files().export_media(fileId=f['id'], mimeType='text/plain').execute().decode('utf-8')
            docs.append(Document(page_content=t, metadata={"source": f['name']}))
        chunks = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100).split_documents(docs)
        FAISS.from_documents(chunks, GoogleGenerativeAIEmbeddings(model="gemini-embedding-001")).save_local("db_ingatan_faiss")
        return "success", len(chunks)
    except Exception as e: return "error", str(e)

# --- 4. TOP BAR: TITLE & BILLING ---
col_t, col_s = st.columns([0.7, 0.3])
with col_t:
    st.title(f"🧠 {st.session_state.current_topic}")

with col_s:
    with st.popover("⚙️ Menu & Billing", use_container_width=True):
        st.subheader("📊 Billing Real-time")
        cost = get_cost_estimate()
        st.metric("Estimasi", f"Rp {cost:,.2f}")
        st.caption(f"Kurs: Rp {st.session_state.kurs_idr:,.0f} | In: {st.session_state.total_tokens_in}")
        
        st.divider()
        st.subheader("📝 Input Memori")
        opts = ["➕ Buat Catatan Baru"] + [f['name'] for f in st.session_state.file_list]
        sel_file = st.selectbox("Update Catatan", opts)
        # (Logika simpan tetap ada di backend Anda)
        
        st.divider()
        sel_model = st.selectbox("Model", ["gemini-2.5-flash", "gemini-2.5-pro"])
        if st.button("🔄 Sync Memori", use_container_width=True):
            status, msg = sync_data()
            if status == "success": st.toast("Data Diserap!", icon="✅")
        
        if st.button("🗑️ Reset Chat", use_container_width=True):
            st.session_state.chats[st.session_state.current_topic] = []
            st.session_state.total_tokens_in = st.session_state.total_tokens_out = 0
            st.rerun()

# --- 5. SIDEBAR: CHAT HISTORY & PINS ---
with st.sidebar:
    st.markdown("<h1 style='text-align: center;'>🧠</h1>", unsafe_allow_html=True)
    
    # TOMBOL CHAT BARU
    if st.button("➕ Chat Baru", use_container_width=True, type="primary"):
        new_id = f"Chat {len(st.session_state.chats) + 1}"
        st.session_state.chats[new_id] = []
        st.session_state.current_topic = new_id
        st.rerun()

    st.divider()

    # SECTION: PINNED TOPICS
    if st.session_state.pinned_topics:
        st.markdown("### 📌 Tersemat")
        for topic in st.session_state.pinned_topics:
            col_p1, col_p2 = st.columns([0.8, 0.2])
            with col_p1:
                if st.button(f"🗨️ {topic}", key=f"pin_{topic}", use_container_width=True):
                    st.session_state.current_topic = topic
                    st.rerun()
            with col_p2:
                if st.button("📍", key=f"unpin_{topic}", help="Lepas Pin"):
                    st.session_state.pinned_topics.remove(topic)
                    st.rerun()
        st.divider()

    # SECTION: REGULAR TOPICS
    st.markdown("### 📚 Riwayat Topik")
    for topic in list(st.session_state.chats.keys()):
        if topic not in st.session_state.pinned_topics:
            col_r1, col_r2 = st.columns([0.8, 0.2])
            with col_r1:
                is_active = "primary" if topic == st.session_state.current_topic else "secondary"
                if st.button(f"🗨️ {topic}", key=f"reg_{topic}", use_container_width=True, type=is_active):
                    st.session_state.current_topic = topic
                    st.rerun()
            with col_r2:
                if st.button("📌", key=f"pin_act_{topic}", help="Sematkan"):
                    st.session_state.pinned_topics.append(topic)
                    st.rerun()

# --- 6. CHAT INTERFACE ---
llm = ChatGoogleGenerativeAI(model=sel_model, temperature=0.3)

for m in st.session_state.chats[st.session_state.current_topic]:
    with st.chat_message(m["role"]): st.markdown(m["content"])

if p := st.chat_input("Tanya asisten..."):
    st.session_state.chats[st.session_state.current_topic].append({"role": "user", "content": p})
    with st.chat_message("user"): st.markdown(p)

    with st.chat_message("assistant"):
        with st.spinner("Mikir..."):
            if not os.path.exists("db_ingatan_faiss"):
                ans = "Sync dulu di Menu!"
            else:
                db = FAISS.load_local("db_ingatan_faiss", GoogleGenerativeAIEmbeddings(model="gemini-embedding-001"), allow_dangerous_deserialization=True)
                ctx = "\n\n".join([d.page_content for d in db.similarity_search(p, k=2)])
                resp = llm.invoke(f"Konteks: {ctx}\n\n Pertanyaan: {p}")
                
                if hasattr(resp, 'usage_metadata'):
                    st.session_state.total_tokens_in += resp.usage_metadata.get('prompt_token_count', 0)
                    st.session_state.total_tokens_out += resp.usage_metadata.get('candidates_token_count', 0)
                
                ans = resp.content[0].get('text', str(resp.content)) if isinstance(resp.content, list) else resp.content
            
            st.markdown(ans)
            st.session_state.chats[st.session_state.current_topic].append({"role": "assistant", "content": ans})
            st.rerun()