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

# --- 1. KONFIGURASI HALAMAN & THEME ---
st.set_page_config(page_title="Otak Kedua Irfanka", page_icon="🧠", layout="wide")

# Ambil data rahasia dari Streamlit Secrets
try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    FOLDER_ID = st.secrets["GDRIVE_FOLDER_ID"]
    creds_info = json.loads(st.secrets["SERVICE_ACCOUNT_JSON"])
    
    # Inisialisasi API Google
    genai.configure(api_key=API_KEY)
    os.environ["GOOGLE_API_KEY"] = API_KEY
except Exception as e:
    st.error("Waduh, cek dashboard Secrets lu. Kayaknya ada yang belum di-input!")
    st.stop()

# --- 2. SIDEBAR (PENGATURAN & MODEL) ---
with st.sidebar:
    st.title("⚙️ Pengaturan")
    
    # Model Selector: Pilih otak AI lu di sini
    selected_model = st.selectbox(
        "Pilih Model AI:",
        ["gemini-2.5-flash", "gemini-1.5-pro"],
        index=0,
        help="Flash: Cepat & Murah (Recommended). Pro: Paling Pinter & Mahal."
    )
    
    st.markdown("---")
    if st.button("🗑️ Hapus Riwayat Chat"):
        st.session_state.messages = []
        st.rerun()

# Inisialisasi Mesin AI (LLM & Embeddings)
embeddings = GoogleGenerativeAIEmbeddings(model="gemini-embedding-001", google_api_key=API_KEY)
llm = ChatGoogleGenerativeAI(model=selected_model, temperature=0.3, google_api_key=API_KEY)
db_path = "db_ingatan_faiss"

# --- 3. FUNGSI LOGIKA (OTAK BELAKANG) ---

def sync_data():
    """Fungsi buat sedot data dari GDocs ke memori FAISS"""
    try:
        creds = service_account.Credentials.from_service_account_info(
            creds_info, scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        service = build('drive', 'v3', credentials=creds)
        
        # Cari file di folder GDrive
        query = f"'{FOLDER_ID}' in parents and trashed=false"
        results = service.files().list(q=query, fields="files(id, name, mimeType)").execute()
        items = results.get('files', [])
        
        if not items:
            return "error", "Foldernya kosong beneran, Bre!"
            
        docs = []
        for item in items:
            # Cuma ambil file Google Docs
            if item['mimeType'] == 'application/vnd.google-apps.document':
                request = service.files().export_media(fileId=item['id'], mimeType='text/plain')
                teks = request.execute().decode('utf-8')
                if teks.strip():
                    docs.append(Document(page_content=teks, metadata={"source": item['name']}))
        
        if not docs:
            return "error", "Gak ada teks yang bisa disedot dari Google Docs lu."

        # Potong-potong teks biar AI gampang bacanya (Chunking)
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        chunks = splitter.split_documents(docs)
        
        # Simpan ke database lokal (FAISS)
        vectorstore = FAISS.from_documents(chunks, embeddings)
        vectorstore.save_local(db_path)
        
        return "success", len(chunks)
    except Exception as e:
        return "error", str(e)

def tanya_ai(pesan):
    """Fungsi buat nanya ke AI pake data dari FAISS"""
    try:
        if not os.path.exists(db_path):
            return "Gue belum punya ingatan. Klik tombol 'Sync' dulu di bawah!"
        
        # Load database FAISS
        db = FAISS.load_local(db_path, embeddings, allow_dangerous_deserialization=True)
        
        # Cari potongan teks yang paling relevan (k=2 buat hemat token)
        results = db.similarity_search(pesan, k=2)
        
        context = "\n\n".join([d.page_content for d in results])
        prompt = f"Gunakan konteks ini untuk menjawab: {context}\n\n Pertanyaan: {pesan}"
        
        # Panggil Gemini
        response = llm.invoke(prompt)
        
        # Bersihkan output (biar gak muncul format kodingan)
        if isinstance(response.content, list):
            return response.content[0].get('text', str(response.content))
        return response.content
    except Exception as e:
        return f"Error pas nanya: {e}"

# --- 4. TAMPILAN CHAT (FRONTEND) ---
st.title("🧠 Otak Kedua Irfanka")

# Inisialisasi riwayat chat di session state
if "messages" not in st.session_state:
    st.session_state.messages = []

# Tampilkan semua pesan dari riwayat
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

# Kotak input chat
if p := st.chat_input("Tanya soal jadwal, strategi parfum, atau data PKL..."):
    # Simpan chat user
    st.session_state.messages.append({"role": "user", "content": p})
    with st.chat_message("user"):
        st.markdown(p)

    # Respon AI
    with st.chat_message("assistant"):
        with st.spinner("Lagi nyari di ingatan..."):
            jawaban = tanya_ai(p)
            st.markdown(jawaban)
            st.session_state.messages.append({"role": "assistant", "content": jawaban})

# --- 5. CONTROL PANEL (FOOTER) ---
st.markdown("---")
col1, col2 = st.columns([1, 4])

with col1:
    if st.button("🔄 Sync Memori"):
        with st.spinner("Menyerap data..."):
            status, msg = sync_data()
            if status == "success":
                st.toast(f"Mantap! {msg} memori berhasil diserap.", icon="✅")
            else:
                st.error(msg)

with col2:
    st.caption(f"📍 Model Aktif: {selected_model} | Status Billing: Pay-as-you-go")