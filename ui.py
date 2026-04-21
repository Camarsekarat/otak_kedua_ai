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
st.set_page_config(page_title="Otak Kedua v3.7", page_icon="🧠", layout="wide")

# GANTI INI dengan email Google utama lu yang punya storage 5 TB
EMAIL_UTAMA = "email_lu_yang_5tb@gmail.com" 

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    FOLDER_ID = st.secrets["GDRIVE_FOLDER_ID"]
    creds_info = json.loads(st.secrets["SERVICE_ACCOUNT_JSON"])
    genai.configure(api_key=API_KEY)
    os.environ["GOOGLE_API_KEY"] = API_KEY
    # Scope harus full drive biar bisa transfer ownership
    SCOPES = ['https://www.googleapis.com/auth/drive']
except:
    st.error("Waduh Bre, cek Secrets lu di Streamlit Dashboard. Ada yang kurang!")
    st.stop()

# --- 2. SESSION STATE ---
if "chats" not in st.session_state:
    st.session_state.chats = {"Chat Utama": []}
if "pinned_topics" not in st.session_state:
    st.session_state.pinned_topics = []
if "current_topic" not in st.session_state:
    st.session_state.current_topic = "Chat Utama"
if "file_list" not in st.session_state:
    st.session_state.file_list = []
if "total_tokens_in" not in st.session_state:
    st.session_state.total_tokens_in = 0
if "total_tokens_out" not in st.session_state:
    st.session_state.total_tokens_out = 0
if "kurs_idr" not in st.session_state:
    st.session_state.kurs_idr = 16000.0

# --- 3. BACKEND FUNCTIONS (G-DRIVE & KURS) ---

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

def simpan_atau_update_memori(file_selection, judul_baru, isi):
    try:
        service = get_drive_service()
        # Biar hemat kuota Service Account (SA), kita pake resumable=False
        if file_selection == "➕ Buat Catatan Baru":
            file_metadata = {
                'name': judul_baru, 
                'parents': [FOLDER_ID], 
                'mimeType': 'application/vnd.google-apps.document'
            }
            media = MediaIoBaseUpload(io.BytesIO(isi.encode('utf-8')), mimetype='text/plain', resumable=False)
            file = service.files().create(body=file_metadata, media_body=media, fields='id', supportsAllDrives=True).execute()
            file_id = file.get('id')
            
            # --- JURUS ANTI QUOTA FULL: TRANSFER OWNERSHIP ---
            permission = {'type': 'user', 'role': 'owner', 'emailAddress': EMAIL_UTAMA}
            service.permissions().create(fileId=file_id, body=permission, transferOwnership=True, supportsAllDrives=True).execute()
        else:
            f_id = next(f['id'] for f in st.session_state.file_list if f['name'] == file_selection)
            old_content = service.files().export_media(fileId=f_id, mimeType='text/plain').execute().decode('utf-8')
            new_text = old_content + "\n\n---\nUpdate:\n" + isi
            media = MediaIoBaseUpload(io.BytesIO(new_text.encode('utf-8')), mimetype='text/plain', resumable=False)
            service.files().update(fileId=f_id, media_body=media, supportsAllDrives=True).execute()
        
        fetch_files()
        return True, "Berhasil! Memori sudah masuk ke ember lu."
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
        
        if not docs: return "error", "Gak ada file teks di folder lu."
        
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        chunks = splitter.split_documents(docs)
        FAISS.from_documents(chunks, GoogleGenerativeAIEmbeddings(model="gemini-embedding-001")).save_local("db_ingatan_faiss")
        return "success", len(chunks)
    except Exception as e: return "error", str(e)

# --- 4. TOP BAR UI ---
col_t, col_s = st.columns([0.7, 0.3])
with col_t:
    st.title(f"🧠 {st.session_state.current_topic}")

with col_s:
    with st.popover("⚙️ Menu & Billing", use_container_width=True):
        st.subheader("📊 Estimasi Biaya")
        st.session_state.kurs_idr = fetch_realtime_kurs()
        price_in = (0.075/1e6) * st.session_state.kurs_idr
        price_out = (0.30/1e6) * st.session_state.kurs_idr
        cost = (st.session_state.total_tokens_in * price_in) + (st.session_state.total_tokens_out * price_out)
        st.metric("Total Biaya", f"Rp {cost:,.2f}")
        st.caption(f"Kurs: 1 USD = Rp {st.session_state.kurs_idr:,.0f}")
        
        st.divider()
        st.subheader("📝 Input Memori")
        fetch_files()
        opts = ["➕ Buat Catatan Baru"] + [f['name'] for f in st.session_state.file_list]
        sel_file = st.selectbox("Pilih Target Catatan", opts)
        
        judul_baru = ""
        if sel_file == "➕ Buat Catatan Baru":
            judul_baru = st.text_input("Nama File Baru", placeholder="Misal: Riset Parfum")
            
        isi_memori = st.text_area("Isi Catatan")
        if st.button("🚀 Simpan ke Drive", use_container_width=True):
            if (sel_file == "➕ Buat Catatan Baru" and not judul_baru) or not isi_memori:
                st.warning("Isi dulu dong datanya!")
            else:
                with st.spinner("Lagi diantar kurir..."):
                    ok, msg = simpan_atau_update_memori(sel_file, judul_baru, isi_memori)
                    if ok: st.success(msg)
                    else: st.error(f"Gagal: {msg}")
        
        st.divider()
        sel_model = st.selectbox("Otak AI", ["gemini-2.5-flash", "gemini-2.5-pro"])
        if st.button("🔄 Sync G-Drive", use_container_width=True):
            status, msg = sync_data()
            if status == "success": st.toast(f"Berhasil serap {msg} data!", icon="✅")
            else: st.error(msg)

# --- 5. SIDEBAR: CHAT HUB ---
with st.sidebar:
    st.markdown("<h1 style='text-align: center;'>🧠</h1>", unsafe_allow_html=True)
    if st.button("➕ Chat Baru", use_container_width=True, type="primary"):
        new_id = f"Chat {len(st.session_state.chats) + 1}"
        st.session_state.chats[new_id] = []
        st.session_state.current_topic = new_id
        st.rerun()
    st.divider()

    def render_topic_item(topic, pinned):
        c1, c2 = st.columns([0.8, 0.2])
        with c1:
            if st.button(f"🗨️ {topic}", key=f"t_{topic}", use_container_width=True, 
                         type="primary" if topic == st.session_state.current_topic else "secondary"):
                st.session_state.current_topic = topic
                st.rerun()
        with c2:
            with st.popover("⋮"):
                # Opsi Pin
                if pinned:
                    if st.button("📍 Lepas Pin", key=f"un_{topic}"):
                        st.session_state.pinned_topics.remove(topic); st.rerun()
                else:
                    if st.button("📌 Sematkan", key=f"pi_{topic}"):
                        st.session_state.pinned_topics.append(topic); st.rerun()
                # Opsi Rename
                new_n = st.text_input("Ganti Nama:", value=topic, key=f"ren_{topic}")
                if st.button("💾 Simpan", key=f"sv_{topic}"):
                    st.session_state.chats[new_n] = st.session_state.chats.pop(topic)
                    if topic in st.session_state.pinned_topics:
                        st.session_state.pinned_topics = [new_n if x == topic else x for x in st.session_state.pinned_topics]
                    st.session_state.current_topic = new_n; st.rerun()
                # Opsi Hapus
                if st.button("🗑️ Hapus", key=f"del_{topic}"):
                    if len(st.session_state.chats) > 1:
                        del st.session_state.chats[topic]
                        if topic in st.session_state.pinned_topics: st.session_state.pinned_topics.remove(topic)
                        st.session_state.current_topic = list(st.session_state.chats.keys())[0]; st.rerun()

    if st.session_state.pinned_topics:
        st.markdown("### 📌 Tersemat")
        for t in st.session_state.pinned_topics: render_topic_item(t, True)
        st.divider()

    st.markdown("### 📚 Riwayat")
    for t in list(st.session_state.chats.keys()):
        if t not in st.session_state.pinned_topics: render_topic_item(t, False)

# --- 6. MAIN CHAT LOGIC ---
llm = ChatGoogleGenerativeAI(model=sel_model, temperature=0.3)

for m in st.session_state.chats[st.session_state.current_topic]:
    with st.chat_message(m["role"]): st.markdown(m["content"])

if p := st.chat_input("Tanya soal jadwal, strategi, atau data sekolah..."):
    st.session_state.chats[st.session_state.current_topic].append({"role": "user", "content": p})
    with st.chat_message("user"): st.markdown(p)

    with st.chat_message("assistant"):
        with st.spinner("Mencari di memori..."):
            if not os.path.exists("db_ingatan_faiss"):
                ans = "Ingatan kosong Bre. Sync G-Drive dulu di menu pengaturan!"
            else:
                db = FAISS.load_local("db_ingatan_faiss", GoogleGenerativeAIEmbeddings(model="gemini-embedding-001"), allow_dangerous_deserialization=True)
                res = db.similarity_search(p, k=2)
                context = "\n\n".join([d.page_content for d in res])
                resp = llm.invoke(f"Konteks: {context}\n\n Pertanyaan: {p}")
                
                # Update Meteran Token
                if hasattr(resp, 'usage_metadata'):
                    st.session_state.total_tokens_in += resp.usage_metadata.get('prompt_token_count', 0)
                    st.session_state.total_tokens_out += resp.usage_metadata.get('candidates_token_count', 0)
                
                ans = resp.content[0].get('text', str(resp.content)) if isinstance(resp.content, list) else resp.content
            
            st.markdown(ans)
            st.session_state.chats[st.session_state.current_topic].append({"role": "assistant", "content": ans})
            st.rerun()