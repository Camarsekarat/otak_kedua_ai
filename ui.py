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
st.set_page_config(page_title="Otak Kedua Irfanka", page_icon="🧠", layout="wide")

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    FOLDER_ID = st.secrets["GDRIVE_FOLDER_ID"]
    creds_info = json.loads(st.secrets["SERVICE_ACCOUNT_JSON"])
    genai.configure(api_key=API_KEY)
    os.environ["GOOGLE_API_KEY"] = API_KEY
    # Ubah scope biar bisa nulis/bikin file di Drive
    SCOPES = ['https://www.googleapis.com/auth/drive']
except Exception as e:
    st.error("Secrets lu bermasalah, Bre!")
    st.stop()

# --- 2. LOGIKA BACKEND ---

def get_drive_service():
    creds = service_account.Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def simpan_memori_baru(judul, isi):
    """Bikin file Google Doc baru langsung di folder tujuan"""
    try:
        service = get_drive_service()
        file_metadata = {
            'name': judul,
            'parents': [FOLDER_ID],
            'mimeType': 'application/vnd.google-apps.document'
        }
        media = MediaIoBaseUpload(io.BytesIO(isi.encode('utf-8')), mimetype='text/plain', resumable=True)
        service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return True, "Memori berhasil disimpan ke G-Drive!"
    except Exception as e:
        return False, str(e)

def sync_data():
    """Sedot data dari GDocs ke FAISS"""
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
                if teks.strip():
                    docs.append(Document(page_content=teks, metadata={"source": item['name']}))
        
        if not docs: return "error", "Gak ada teks di Google Docs."

        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        chunks = splitter.split_documents(docs)
        vectorstore = FAISS.from_documents(chunks, embeddings)
        vectorstore.save_local("db_ingatan_faiss")
        return "success", len(chunks)
    except Exception as e:
        return "error", str(e)

# Inisialisasi AI
embeddings = GoogleGenerativeAIEmbeddings(model="gemini-embedding-001", google_api_key=API_KEY)
db_path = "db_ingatan_faiss"

# --- 3. SIDEBAR (LOGO, INPUT, SETTINGS) ---
with st.sidebar:
    st.markdown("<h1 style='text-align: center;'>🧠</h1>", unsafe_allow_html=True)
    st.title("Otak Kedua")
    
    # Fitur Input Baru
    st.markdown("---")
    st.subheader("📝 Catat Memori Baru")
    new_title = st.text_input("Judul Catatan (misal: Ide Konten Senin)")
    new_content = st.text_area("Apa yang mau diingat?", placeholder="Tulis strategi parfum atau jadwal baru di sini...")
    
    if st.button("🚀 Simpan ke Drive", use_container_width=True):
        if new_title and new_content:
            with st.spinner("Mengirim ke Drive..."):
                ok, msg = simpan_memori_baru(new_title, new_content)
                if ok: st.success(msg)
                else: st.error(msg)
        else:
            st.warning("Judul dan isi jangan kosong, Bre!")

    # Push Settings to Bottom
    st.markdown("<div style='margin-top: 15vh;'></div>", unsafe_allow_html=True)
    st.markdown("---")
    st.subheader("⚙️ Pengaturan")
    
    selected_model = st.selectbox("Pilih Otak AI:", ["gemini-2.5-flash", "gemini-2.5-pro"])
    llm = ChatGoogleGenerativeAI(model=selected_model, temperature=0.3, google_api_key=API_KEY)
    
    if st.button("🔄 Sync Memori", use_container_width=True):
        with st.spinner("Menyerap data..."):
            status, msg = sync_data()
            if status == "success": st.toast(f"Berhasil serap {msg} data!", icon="✅")
            else: st.error(msg)
            
    if st.button("🗑️ Hapus Chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

# --- 4. MAIN CHAT UI ---
st.markdown("<h1>🤖 Chat Assistant</h1>", unsafe_allow_html=True)
st.caption(f"📍 Model: {selected_model}")

if "messages" not in st.session_state:
    st.session_state.messages = []

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

if p := st.chat_input("Tanya soal jadwal atau strategi @irfankaisa..."):
    st.session_state.messages.append({"role": "user", "content": p})
    with st.chat_message("user"): st.markdown(p)

    with st.chat_message("assistant"):
        with st.spinner("Mencari jawaban..."):
            # Logika tanya_ai terintegrasi di sini
            if not os.path.exists(db_path):
                jawaban = "Ingatan kosong. Sync dulu di sidebar!"
            else:
                db = FAISS.load_local(db_path, embeddings, allow_dangerous_deserialization=True)
                results = db.similarity_search(p, k=2)
                context = "\n\n".join([d.page_content for d in results])
                prompt = f"Konteks: {context}\n\nPertanyaan: {p}"
                response = llm.invoke(prompt)
                jawaban = response.content[0].get('text', str(response.content)) if isinstance(response.content, list) else response.content
            
            st.markdown(jawaban)
            st.session_state.messages.append({"role": "assistant", "content": jawaban})