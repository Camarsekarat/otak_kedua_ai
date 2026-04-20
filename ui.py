import streamlit as st
import os
import json
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS

# --- 1. SETUP & CONFIG ---
st.set_page_config(page_title="Otak Kedua Irfanka", page_icon="🧠", layout="wide")

# Ambil Secrets
try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    FOLDER_ID = st.secrets["GDRIVE_FOLDER_ID"]
    creds_info = json.loads(st.secrets["SERVICE_ACCOUNT_JSON"])
    genai.configure(api_key=API_KEY)
    os.environ["GOOGLE_API_KEY"] = API_KEY
except Exception as e:
    st.error("Settingan Secrets lu ada yang kurang, Bre!")
    st.stop()

# --- 2. MODEL SELECTION (SIDEBAR) ---
with st.sidebar:
    st.title("⚙️ Pengaturan")
    selected_model = st.selectbox(
        "Pilih Otak AI:",
        [
            "gemini-1.5-flash", 
            "gemini-1.5-pro", 
            "gemini-3.1-flash-image-preview"
        ],
        index=2,
        help="Flash = Cepat, Pro = Lebih Pinter tapi lambat."
    )
    st.markdown("---")
    if st.button("🗑️ Hapus Riwayat Chat"):
        st.session_state.messages = []
        st.rerun()

# Inisialisasi Model berdasarkan pilihan
embeddings = GoogleGenerativeAIEmbeddings(model="gemini-embedding-001", google_api_key=API_KEY)
llm = ChatGoogleGenerativeAI(model=selected_model, temperature=0.3, google_api_key=API_KEY)
db_path = "db_ingatan_faiss"

# --- 3. FUNGSI LOGIKA ---
def sync_data():
    try:
        creds = service_account.Credentials.from_service_account_info(
            creds_info, scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        service = build('drive', 'v3', credentials=creds)
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
        
        if not docs: return "error", "Gak ada teks Google Docs."

        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        chunks = splitter.split_documents(docs)
        vectorstore = FAISS.from_documents(chunks, embeddings)
        vectorstore.save_local(db_path)
        return "success", len(chunks)
    except Exception as e:
        return "error", str(e)

def tanya_ai(pesan):
    try:
        if not os.path.exists(db_path):
            return "Gue belum punya ingatan. Klik 'Sync' dulu di bawah!"
        
        db = FAISS.load_local(db_path, embeddings, allow_dangerous_deserialization=True)
        results = db.similarity_search(pesan, k=3)
        context = "\n\n".join([d.page_content for d in results])
        prompt = f"Gunakan konteks ini: {context}\n\nPertanyaan: {pesan}"
        
        response = llm.invoke(prompt)
        if isinstance(response.content, list):
            return response.content[0].get('text', str(response.content))
        return response.content
    except Exception as e:
        return f"Error: {e}"

# --- 4. UI CHAT HISTORY ---
st.title("🧠 Otak Kedua (Live)")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Tampilkan Riwayat
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

# Input Chat
if p := st.chat_input("Tanya soal jadwal atau konten..."):
    st.session_state.messages.append({"role": "user", "content": p})
    with st.chat_message("user"):
        st.markdown(p)

    with st.chat_message("assistant"):
        with st.spinner("Mikir..."):
            jawaban = tanya_ai(p)
            st.markdown(jawaban)
            st.session_state.messages.append({"role": "assistant", "content": jawaban})

# --- 5. CONTROL PANEL (DI BAWAH) ---
st.markdown("---")
col1, col2 = st.columns([1, 4])
with col1:
    if st.button("🔄 Sync G-Drive"):
        with st.spinner("Lagi nyerap data..."):
            status, msg = sync_data()
            if status == "success":
                st.toast(f"Berhasil menyerap {msg} memori!", icon="✅")
            else:
                st.error(msg)
with col2:
    st.caption(f"📍 Menggunakan model: {selected_model} | Database: FAISS")