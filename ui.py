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
st.set_page_config(page_title="Otak Kedua v3.1", page_icon="🧠", layout="wide")

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    FOLDER_ID = st.secrets["GDRIVE_FOLDER_ID"]
    creds_info = json.loads(st.secrets["SERVICE_ACCOUNT_JSON"])
    genai.configure(api_key=API_KEY)
    os.environ["GOOGLE_API_KEY"] = API_KEY
    SCOPES = ['https://www.googleapis.com/auth/drive']
except:
    st.error("Cek Secrets lu dulu di Dashboard Streamlit Cloud!")
    st.stop()

# --- 2. SESSION STATE ---
if "chats" not in st.session_state:
    st.session_state.chats = {"Utama": []}
if "current_topic" not in st.session_state:
    st.session_state.current_topic = "Utama"
if "file_list" not in st.session_state:
    st.session_state.file_list = [] # Buat nyimpen daftar judul GDocs

# --- 3. BACKEND FUNCTIONS ---
def get_drive_service():
    creds = service_account.Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def fetch_files():
    """Ambil daftar nama file buat dropdown"""
    try:
        service = get_drive_service()
        query = f"'{FOLDER_ID}' in parents and trashed=false and mimeType='application/vnd.google-apps.document'"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        st.session_state.file_list = results.get('files', [])
    except:
        st.session_state.file_list = []

def simpan_atau_update_memori(file_selection, judul_baru, isi):
    try:
        service = get_drive_service()
        # Jika Pilih Buat Baru
        if file_selection == "➕ Buat Catatan Baru":
            file_metadata = {'name': judul_baru, 'parents': [FOLDER_ID], 'mimeType': 'application/vnd.google-apps.document'}
            media = MediaIoBaseUpload(io.BytesIO(isi.encode('utf-8')), mimetype='text/plain', resumable=True)
            service.files().create(body=file_metadata, media_body=media).execute()
        else:
            # Cari ID File yang dipilih
            file_id = next(f['id'] for f in st.session_state.file_list if f['name'] == file_selection)
            # Ambil teks lama
            old_content = service.files().export_media(fileId=file_id, mimeType='text/plain').execute().decode('utf-8')
            # Gabungin (Append)
            new_full_content = old_content + "\n\n---\n" + isi
            media = MediaIoBaseUpload(io.BytesIO(new_full_content.encode('utf-8')), mimetype='text/plain', resumable=True)
            service.files().update(fileId=file_id, media_body=media).execute()
            
        fetch_files() # Refresh list
        return True, "Memori berhasil diupdate!"
    except Exception as e: return False, str(e)

def sync_data():
    try:
        service = get_drive_service()
        fetch_files() # Pastiin list file terbaru
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

# Jalankan fetch file sekali di awal
if not st.session_state.file_list:
    fetch_files()

# --- 4. HEADER & SETTINGS POPOVER ---
col_t, col_s = st.columns([0.8, 0.2])
with col_t:
    st.title(f"🧠 {st.session_state.current_topic}")

with col_s:
    with st.popover("⚙️ Menu", use_container_width=True):
        st.subheader("📝 Input Memori")
        # DROPDOWN SESUAI REVISI LU
        options = ["➕ Buat Catatan Baru"] + [f['name'] for f in st.session_state.file_list]
        selected_file = st.selectbox("Pilih Judul Catatan", options)
        
        judul_input = ""
        if selected_file == "➕ Buat Catatan Baru":
            judul_input = st.text_input("Nama File Baru", placeholder="Misal: Naskah Iklan Parfum")
        
        isi_catatan = st.text_area("Isi Catatan", placeholder="Tambahkan poin-poin penting di sini...")
        
        if st.button("🚀 Simpan ke G-Drive", use_container_width=True):
            if (selected_file == "➕ Buat Catatan Baru" and not judul_input) or not isi_catatan:
                st.warning("Lengkapi data dulu, Bre!")
            else:
                with st.spinner("Proses..."):
                    ok, msg = simpan_atau_update_memori(selected_file, judul_input, isi_catatan)
                    if ok: st.success(msg)
                    else: st.error(msg)
        
        st.divider()
        st.subheader("🛠️ Sistem")
        sel_model = st.selectbox("Model", ["gemini-2.5-flash", "gemini-2.5-pro"])
        if st.button("🔄 Sync Memori (RAG)", use_container_width=True):
            status, msg = sync_data()
            if status == "success": st.toast(f"Berhasil serap {msg} data!", icon="✅")
            else: st.error(msg)
        
        if st.button("🗑️ Reset Chat", use_container_width=True):
            st.session_state.chats[st.session_state.current_topic] = []
            st.rerun()

# --- 5. SIDEBAR: TOPICS ---
with st.sidebar:
    st.markdown("### 📚 Riwayat Topik")
    new_t = st.text_input("➕ Tambah Topik:", placeholder="Misal: Evaluasi Iklan")
    if st.button("Buat Topik"):
        if new_t and new_t not in st.session_state.chats:
            st.session_state.chats[new_t] = []
            st.session_state.current_topic = new_t
            st.rerun()
    st.divider()
    for topic in list(st.session_state.chats.keys()):
        if st.button(f"🗨️ {topic}", use_container_width=True, 
                     type="primary" if topic == st.session_state.current_topic else "secondary"):
            st.session_state.current_topic = topic
            st.rerun()

# --- 6. CHAT INTERFACE ---
llm = ChatGoogleGenerativeAI(model=sel_model, temperature=0.3)

for m in st.session_state.chats[st.session_state.current_topic]:
    with st.chat_message(m["role"]): st.markdown(m["content"])

if p := st.chat_input("Tanya asisten..."):
    st.session_state.chats[st.session_state.current_topic].append({"role": "user", "content": p})
    with st.chat_message("user"): st.markdown(p)

    with st.chat_message("assistant"):
        with st.spinner("Mencari..."):
            if not os.path.exists("db_ingatan_faiss"):
                ans = "Ingatan kosong. Sync dulu di Menu!"
            else:
                db = FAISS.load_local("db_ingatan_faiss", GoogleGenerativeAIEmbeddings(model="gemini-embedding-001"), allow_dangerous_deserialization=True)
                res = db.similarity_search(p, k=2)
                context = "\n\n".join([d.page_content for d in res])
                resp = llm.invoke(f"Konteks: {context}\n\n Pertanyaan: {p}")
                ans = resp.content[0].get('text', str(resp.content)) if isinstance(resp.content, list) else resp.content
            
            st.markdown(ans)
            st.session_state.chats[st.session_state.current_topic].append({"role": "assistant", "content": ans})