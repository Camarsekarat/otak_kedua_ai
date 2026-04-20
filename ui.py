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
st.set_page_config(page_title="Otak Kedua v3.3", page_icon="🧠", layout="wide")

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    FOLDER_ID = st.secrets["GDRIVE_FOLDER_ID"]
    creds_info = json.loads(st.secrets["SERVICE_ACCOUNT_JSON"])
    genai.configure(api_key=API_KEY)
    os.environ["GOOGLE_API_KEY"] = API_KEY
    SCOPES = ['https://www.googleapis.com/auth/drive']
except:
    st.error("Secrets belum lengkap!")
    st.stop()

# --- 2. SESSION STATE (TAMBAHAN KURS) ---
if "chats" not in st.session_state:
    st.session_state.chats = {"Utama": []}
if "current_topic" not in st.session_state:
    st.session_state.current_topic = "Utama"
if "file_list" not in st.session_state:
    st.session_state.file_list = []
if "total_tokens_in" not in st.session_state:
    st.session_state.total_tokens_in = 0
if "total_tokens_out" not in st.session_state:
    st.session_state.total_tokens_out = 0
# Simpan Kurs di Session State biar gak fetch terus-terusan
if "kurs_idr" not in st.session_state:
    st.session_state.kurs_idr = 16000.0  # Default awal

# --- 3. BACKEND FUNCTIONS ---

@st.cache_data(ttl=3600) # Update kurs tiap 1 jam sekali aja biar gak lemot
def fetch_realtime_kurs():
    try:
        # Pake API gratisan tanpa key
        response = requests.get("https://api.exchangerate-api.com/v4/latest/USD")
        data = response.json()
        return float(data["rates"]["IDR"])
    except:
        return 16000.0 # Balik ke default kalau API internet gangguan

def get_cost_estimate():
    # Update kurs ke state
    st.session_state.kurs_idr = fetch_realtime_kurs()
    
    # Harga Gemini 2.5 Flash
    price_in_usd = 0.075 / 1000000
    price_out_usd = 0.30 / 1000000
    
    total_usd = (st.session_state.total_tokens_in * price_in_usd) + \
                (st.session_state.total_tokens_out * price_out_usd)
    
    return total_usd * st.session_state.kurs_idr

# --- (Fungsi G-Drive & Sync tetep sama kayak sebelumnya) ---
def get_drive_service():
    creds = service_account.Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def fetch_files():
    try:
        service = get_drive_service()
        query = f"'{FOLDER_ID}' in parents and trashed=false and mimeType='application/vnd.google-apps.document'"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        st.session_state.file_list = results.get('files', [])
    except: st.session_state.file_list = []

def sync_data():
    try:
        service = get_drive_service()
        fetch_files()
        docs = []
        for f in st.session_state.file_list:
            request = service.files().export_media(fileId=f['id'], mimeType='text/plain')
            teks = request.execute().decode('utf-8')
            docs.append(Document(page_content=teks, metadata={"source": f['name']}))
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        chunks = splitter.split_documents(docs)
        vectorstore = FAISS.from_documents(chunks, GoogleGenerativeAIEmbeddings(model="gemini-embedding-001"))
        vectorstore.save_local("db_ingatan_faiss")
        return "success", len(chunks)
    except Exception as e: return "error", str(e)

# --- 4. HEADER & SETTINGS ---
col_t, col_s = st.columns([0.7, 0.3])
with col_t:
    st.title(f"🧠 {st.session_state.current_topic}")

with col_s:
    with st.popover("⚙️ Menu & Billing", use_container_width=True):
        # MONITORING BIAYA REAL-TIME
        st.subheader("📊 Penggunaan Hari Ini")
        cost_idr = get_cost_estimate()
        st.metric("Estimasi Biaya", f"Rp {cost_idr:,.2f}")
        st.caption(f"Kurs Real-time: 1 USD = Rp {st.session_state.kurs_idr:,.0f}")
        st.caption(f"In: {st.session_state.total_tokens_in} | Out: {st.session_state.total_tokens_out}")
        
        st.divider()
        st.subheader("📝 Input Memori")
        options = ["➕ Buat Catatan Baru"] + [f['name'] for f in st.session_state.file_list]
        selected_file = st.selectbox("Pilih Catatan", options)
        # ... (Logika input catatan tetap sama) ...
        
        st.divider()
        st.subheader("🛠️ Sistem")
        sel_model = st.selectbox("Model AI", ["gemini-2.5-flash", "gemini-2.5-pro"])
        if st.button("🔄 Sync Memori (RAG)", use_container_width=True):
            status, msg = sync_data()
            if status == "success": st.toast(f"Berhasil serap {msg} data!", icon="✅")
        
        if st.button("🗑️ Reset Chat & Meteran", use_container_width=True):
            st.session_state.chats[st.session_state.current_topic] = []
            st.session_state.total_tokens_in = 0
            st.session_state.total_tokens_out = 0
            st.rerun()

# --- 5. SIDEBAR ---
with st.sidebar:
    st.markdown("### 📚 Riwayat Topik")
    # ... (Logika riwayat topik sama) ...

# --- 6. CHAT LOGIC ---
llm = ChatGoogleGenerativeAI(model=sel_model, temperature=0.3)

for m in st.session_state.chats[st.session_state.current_topic]:
    with st.chat_message(m["role"]): st.markdown(m["content"])

if p := st.chat_input("Tanya asisten..."):
    st.session_state.chats[st.session_state.current_topic].append({"role": "user", "content": p})
    with st.chat_message("user"): st.markdown(p)

    with st.chat_message("assistant"):
        with st.spinner("Mikir..."):
            if not os.path.exists("db_ingatan_faiss"):
                ans = "Sync dulu, Bre!"
            else:
                db = FAISS.load_local("db_ingatan_faiss", GoogleGenerativeAIEmbeddings(model="gemini-embedding-001"), allow_dangerous_deserialization=True)
                res = db.similarity_search(p, k=2)
                context = "\n\n".join([d.page_content for d in res])
                
                # Gunakan invoke dan tangkap usage_metadata
                resp = llm.invoke(f"Konteks: {context}\n\n Pertanyaan: {p}")
                
                # Update Token Counter
                if hasattr(resp, 'usage_metadata'):
                    st.session_state.total_tokens_in += resp.usage_metadata.get('prompt_token_count', 0)
                    st.session_state.total_tokens_out += resp.usage_metadata.get('candidates_token_count', 0)
                
                ans = resp.content[0].get('text', str(resp.content)) if isinstance(resp.content, list) else resp.content
            
            st.markdown(ans)
            st.session_state.chats[st.session_state.current_topic].append({"role": "assistant", "content": ans})
            st.rerun()