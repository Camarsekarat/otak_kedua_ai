import streamlit as st
import os
import json
import io
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS

# --- 1. CONFIG & SECRETS ---
st.set_page_config(page_title="Otak Kedua v3", page_icon="🧠", layout="wide")

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    FOLDER_ID = st.secrets["GDRIVE_FOLDER_ID"]
    creds_info = json.loads(st.secrets["SERVICE_ACCOUNT_JSON"])
    genai.configure(api_key=API_KEY)
    os.environ["GOOGLE_API_KEY"] = API_KEY
    SCOPES = ['https://www.googleapis.com/auth/drive']
except:
    st.error("Cek Secrets lu dulu, Bre!")
    st.stop()

# --- 2. INITIALIZE SESSION STATE (DATABASE LOKAL) ---
if "chats" not in st.session_state:
    st.session_state.chats = {"Utama": []}  # Format: {TopicName: [Messages]}
if "current_topic" not in st.session_state:
    st.session_state.current_topic = "Utama"

# --- 3. BACKEND FUNCTIONS ---
def get_drive_service():
    creds = service_account.Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def simpan_memori_baru(judul, isi):
    try:
        service = get_drive_service()
        file_metadata = {'name': judul, 'parents': [FOLDER_ID], 'mimeType': 'application/vnd.google-apps.document'}
        media = MediaIoBaseUpload(io.BytesIO(isi.encode('utf-8')), mimetype='text/plain', resumable=True)
        service.files().create(body=file_metadata, media_body=media).execute()
        return True, "Memori tersimpan!"
    except Exception as e: return False, str(e)

def sync_data():
    try:
        service = get_drive_service()
        query = f"'{FOLDER_ID}' in parents and trashed=false"
        results = service.files().list(q=query, fields="files(id, name, mimeType)").execute()
        items = results.get('files', [])
        if not items: return "error", "Folder kosong!"
        
        docs = []
        for item in items:
            if item['mimeType'] == 'application/vnd.google-apps.document':
                request = service.files().export_media(fileId=item['id'], mimeType='text/plain')
                teks = request.execute().decode('utf-8')
                docs.append(Document(page_content=teks, metadata={"source": item['name']}))
        
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        chunks = splitter.split_documents(docs)
        vectorstore = FAISS.from_documents(chunks, GoogleGenerativeAIEmbeddings(model="gemini-embedding-001"))
        vectorstore.save_local("db_ingatan_faiss")
        return "success", len(chunks)
    except Exception as e: return "error", str(e)

# --- 4. HEADER & SETTINGS POP OVER (REVISI: MENU TERPISAH) ---
col_title, col_settings = st.columns([0.85, 0.15])

with col_title:
    st.title(f"🧠 {st.session_state.current_topic}")

with col_settings:
    # Ini "Menu Pengaturan" yang lu minta, clean & tersembunyi
    with st.popover("⚙️ Menu", use_container_width=True):
        st.subheader("📝 Input Memori")
        new_title = st.text_input("Judul Catatan")
        new_content = st.text_area("Isi Catatan")
        if st.button("🚀 Simpan ke Drive"):
            if new_title and new_content:
                ok, msg = simpan_memori_baru(new_title, new_content)
                if ok: st.success(msg)
                else: st.error(msg)
        
        st.divider()
        st.subheader("🛠️ Sistem")
        selected_model = st.selectbox("Model AI", ["gemini-2.5-flash", "gemini-2.5-pro"])
        if st.button("🔄 Sync G-Drive"):
            status, msg = sync_data()
            if status == "success": st.toast(f"Serap {msg} data!", icon="✅")
            else: st.error(msg)
        
        if st.button("🗑️ Reset Chat Ini"):
            st.session_state.chats[st.session_state.current_topic] = []
            st.rerun()

# --- 5. SIDEBAR: CHAT HISTORY & TOPICS ---
with st.sidebar:
    st.markdown("### 📚 Riwayat Topik")
    
    # Tambah Topik Baru
    new_topic_name = st.text_input("➕ Tambah Topik:", placeholder="Misal: Iklan TikTok")
    if st.button("Buat Topik Baru"):
        if new_topic_name and new_topic_name not in st.session_state.chats:
            st.session_state.chats[new_topic_name] = []
            st.session_state.current_topic = new_topic_name
            st.rerun()
    
    st.divider()
    
    # List Topik (Pilih Riwayat)
    for topic in list(st.session_state.chats.keys()):
        if st.button(f"🗨️ {topic}", use_container_width=True, 
                     type="primary" if topic == st.session_state.current_topic else "secondary"):
            st.session_state.current_topic = topic
            st.rerun()

# --- 6. CHAT INTERFACE ---
llm = ChatGoogleGenerativeAI(model=selected_model, temperature=0.3)

# Tampilkan pesan di topik yang dipilih
for m in st.session_state.chats[st.session_state.current_topic]:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

if p := st.chat_input("Tanya sesuatu..."):
    # Simpan ke riwayat topik aktif
    st.session_state.chats[st.session_state.current_topic].append({"role": "user", "content": p})
    with st.chat_message("user"): st.markdown(p)

    with st.chat_message("assistant"):
        with st.spinner("Mencari di memori..."):
            if not os.path.exists("db_ingatan_faiss"):
                jawaban = "Ingatan kosong. Klik Sync di menu Pengaturan!"
            else:
                db = FAISS.load_local("db_ingatan_faiss", GoogleGenerativeAIEmbeddings(model="gemini-embedding-001"), allow_dangerous_deserialization=True)
                results = db.similarity_search(p, k=2)
                context = "\n\n".join([d.page_content for d in results])
                response = llm.invoke(f"Konteks: {context}\n\n Pertanyaan: {p}")
                jawaban = response.content[0].get('text', str(response.content)) if isinstance(response.content, list) else response.content
            
            st.markdown(jawaban)
            st.session_state.chats[st.session_state.current_topic].append({"role": "assistant", "content": jawaban})