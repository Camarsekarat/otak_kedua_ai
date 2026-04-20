import streamlit as st
import os
import json
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build

# LangChain & AI
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS

# --- 1. KONFIGURASI SECRETS (PONDASI AWAL) ---
# Pastikan nama-nama ini sama dengan yang lu ketik di dashboard Secrets Streamlit
try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    FOLDER_ID = st.secrets["GDRIVE_FOLDER_ID"]
    # Credentials JSON dari GDrive (Teks JSON mentah)
    creds_info = json.loads(st.secrets["SERVICE_ACCOUNT_JSON"])
    
    # Setup AI
    genai.configure(api_key=API_KEY)
    os.environ["GOOGLE_API_KEY"] = API_KEY
except KeyError as e:
    st.error(f"Waduh Bre, Secret {e} belum lu setting di Streamlit Cloud!")
    st.stop()

# Inisialisasi Model
embeddings = GoogleGenerativeAIEmbeddings(model="gemini-embedding-001")
llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-image-preview", temperature=0.3)
db_path = "db_ingatan_faiss"

# --- 2. FUNGSI LOGIKA (OTAK) ---

def sync_data():
    """Sedot data dari GDocs ke FAISS"""
    try:
        creds = service_account.Credentials.from_service_account_info(
            creds_info, scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        service = build('drive', 'v3', credentials=creds)
        
        query = f"'{FOLDER_ID}' in parents and trashed=false"
        results = service.files().list(q=query, fields="files(id, name, mimeType)").execute()
        items = results.get('files', [])
        
        if not items:
            return "error", "Foldernya kosong, Bre!"
            
        docs = []
        for item in items:
            if item['mimeType'] == 'application/vnd.google-apps.document':
                request = service.files().export_media(fileId=item['id'], mimeType='text/plain')
                teks = request.execute().decode('utf-8')
                if teks.strip():
                    docs.append(Document(page_content=teks, metadata={"source": item['name']}))
        
        if not docs:
            return "error", "Gak ada teks yang bisa disedot."

        # Potong & Simpan
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
            return "Waduh, gue belum punya ingatan. Klik 'Sync' dulu di sebelah kiri!"
        
        db = FAISS.load_local(db_path, embeddings, allow_dangerous_deserialization=True)
        results = db.similarity_search(pesan, k=3)
        
        context = "\n\n".join([d.page_content for d in results])
        
        # INI DIA: Pastiin baris ini ada sebelum llm.invoke
        prompt = f"Gunakan konteks ini untuk menjawab: {context}\n\n Pertanyaan: {pesan}"
        
        response = llm.invoke(prompt)
        
        # Saringan biar nggak muncul format list kodingan
        if isinstance(response.content, list):
            return response.content[0].get('text', str(response.content))
        return response.content
    except Exception as e:
        return f"Error pas nanya: {e}"
# --- 3. UI STREAMLIT (WAJAH) ---

st.set_page_config(page_title="Otak Kedua Irfanka", page_icon="🧠")
st.title("🧠 Otak Kedua AI (Live Edition)")

# Sidebar Control
with st.sidebar:
    st.header("⚙️ Control Panel")
    if st.button("🔄 Sync Memori G-Drive"):
        status, msg = sync_data()
        if status == "success":
            st.success(f"Mantap! {msg} memori berhasil diserap.")
        else:
            st.error(f"Gagal: {msg}")

# Chat System
if "messages" not in st.session_state:
    st.session_state.messages = []

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

if p := st.chat_input("Tanya soal jadwal upload..."):
    st.session_state.messages.append({"role": "user", "content": p})
    with st.chat_message("user"):
        st.markdown(p)

    with st.chat_message("assistant"):
        jawaban = tanya_ai(p)
        st.markdown(jawaban)
        st.session_state.messages.append({"role": "assistant", "content": jawaban})