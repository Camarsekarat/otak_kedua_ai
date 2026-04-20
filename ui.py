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
st.set_page_config(page_title="Otak Kedua v3.6", page_icon="🧠", layout="wide")

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    FOLDER_ID = st.secrets["GDRIVE_FOLDER_ID"]
    creds_info = json.loads(st.secrets["SERVICE_ACCOUNT_JSON"])
    genai.configure(api_key=API_KEY)
    os.environ["GOOGLE_API_KEY"] = API_KEY
    SCOPES = ['https://www.googleapis.com/auth/drive']
except:
    st.error("Cek Secrets lu dulu di Dashboard Streamlit!")
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

# --- 3. BACKEND FUNCTIONS ---

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
        st.session_state.file_list = service.files().list(q=q, fields="files(id, name)").execute().get('files', [])
    except: st.session_state.file_list = []

def simpan_atau_update_memori(file_selection, judul_baru, isi):
    try:
        service = get_drive_service()
        # GANTI INI: Masukin email Google utama lu yang punya 5 TB itu
        EMAIL_UTAMA = "email_lu_yang_5tb@gmail.com" 

        if file_selection == "➕ Buat Catatan Baru":
            file_metadata = {
                'name': judul_baru, 
                'parents': [FOLDER_ID], 
                'mimeType': 'application/vnd.google-apps.document'
            }
            media = MediaIoBaseUpload(io.BytesIO(isi.encode('utf-8')), mimetype='text/plain', resumable=True)
            file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            file_id = file.get('id')

            # --- JURUS PINDAH EMBER ---
            # Kita kasih izin 'owner' ke email utama lu
            permission = {
                'type': 'user',
                'role': 'owner',
                'emailAddress': EMAIL_UTAMA
            }
            # transferOwnership=True wajib buat mindahin beban kuota
            service.permissions().create(fileId=file_id, body=permission, transferOwnership=True).execute()

        else:
            # Kalau update file lama, biasanya owner-nya udah lu (kalo udah di-transfer sebelumnya)
            # Jadi aman, tinggal update aja.
            file_id = next(f['id'] for f in st.session_state.file_list if f['name'] == file_selection)
            old = service.files().export_media(fileId=file_id, mimeType='text/plain').execute().decode('utf-8')
            new_text = old + "\n\n---\nUpdate:\n" + isi
            media = MediaIoBaseUpload(io.BytesIO(new_text.encode('utf-8')), mimetype='text/plain', resumable=True)
            service.files().update(fileId=file_id, media_body=media).execute()
            
        fetch_files()
        return True, "Memori tersimpan di ember lu, Bre!"
    except Exception as e: 
        return False, f"Gagal pindah ember: {e}"
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

def kosongkan_sampah_kurir():
    try:
        service = get_drive_service()
        # Perintah sakti buat ngosongin sampah si Service Account
        service.files().emptyTrash().execute()
        return True, "Sampah kurir berhasil dibuang! Ransel kosong lagi."
    except Exception as e:
        return False, f"Gagal bersih-bersih: {e}"

# --- Di bagian Menu & Billing (Popover), tambahin tombol ini ---
with st.popover("⚙️ Menu & Billing", use_container_width=True):
    # ... (kodingan billing lu yang lama) ...
    
    st.divider()
    st.subheader("🧹 Maintenance")
    if st.button("🗑️ Kosongkan Sampah Kurir (Fix 403)", use_container_width=True):
        ok, msg = kosongkan_sampah_kurir()
        if ok: st.success(msg)
        else: st.error(msg)

def hard_reset_kurir():
    try:
        service = get_drive_service()
        # 1. Kosongkan sampah permanen
        service.files().emptyTrash().execute()
        
        # 2. Cek kuota asli (buat pembuktian logis)
        about = service.about().get(fields="storageQuota").execute()
        usage = int(about['storageQuota']['usage']) / (1024**3) # Convert ke GB
        limit = int(about['storageQuota']['limit']) / (1024**3)
        
        return f"Sampah dibuang. Penggunaan: {usage:.2f} GB / {limit:.2f} GB"
    except Exception as e:
        return f"Gagal: {e}"

# Panggil fungsi ini lewat satu tombol sementara di UI
if st.button("🚨 FIX QUOTA (Hard Reset)"):
    hasil = hard_reset_kurir()
    st.write(hasil)

# --- 4. TOP BAR UI ---
col_t, col_s = st.columns([0.7, 0.3])
with col_t:
    st.title(f"🧠 {st.session_state.current_topic}")

with col_s:
    with st.popover("⚙️ Menu & Billing", use_container_width=True):
        st.subheader("📊 Billing Real-time")
        st.session_state.kurs_idr = fetch_realtime_kurs()
        price_in = (0.075/1e6) * st.session_state.kurs_idr
        price_out = (0.30/1e6) * st.session_state.kurs_idr
        cost = (st.session_state.total_tokens_in * price_in) + (st.session_state.total_tokens_out * price_out)
        st.metric("Estimasi Biaya", f"Rp {cost:,.2f}")
        
        st.divider()
        st.subheader("📝 Input Memori")
        fetch_files() # Refresh daftar file
        opts = ["➕ Buat Catatan Baru"] + [f['name'] for f in st.session_state.file_list]
        sel_file = st.selectbox("Pilih Catatan", opts)
        
        # --- FIX: LOGIKA JUDUL BARU DISINI ---
        judul_input = ""
        if sel_file == "➕ Buat Catatan Baru":
            judul_input = st.text_input("Nama Catatan Baru", placeholder="Misal: Strategi Iklan")
        
        isi_input = st.text_area("Isi Catatan")
        
        if st.button("🚀 Simpan ke Drive", use_container_width=True):
            if (sel_file == "➕ Buat Catatan Baru" and not judul_input) or not isi_input:
                st.warning("Data belum lengkap!")
            else:
                with st.spinner("Proses..."):
                    ok, msg = simpan_atau_update_memori(sel_file, judul_input, isi_input)
                    if ok: st.success(msg)
                    else: st.error(msg)
        
        st.divider()
        sel_model = st.selectbox("Model", ["gemini-2.5-flash", "gemini-2.5-pro"])
        if st.button("🔄 Sync G-Drive", use_container_width=True):
            status, msg = sync_data()
            if status == "success": st.toast("Berhasil Sync!", icon="✅")

# --- 5. SIDEBAR: THE CHAT HUB ---
with st.sidebar:
    st.markdown("<h1 style='text-align: center;'>🧠</h1>", unsafe_allow_html=True)
    if st.button("➕ Chat Baru", use_container_width=True, type="primary"):
        new_name = f"Chat {len(st.session_state.chats) + 1}"
        st.session_state.chats[new_name] = []
        st.session_state.current_topic = new_name
        st.rerun()
    st.divider()

    # Function to render topic items with Hover Menu
    def render_topic(topic, pinned):
        c1, c2 = st.columns([0.8, 0.2])
        with c1:
            st.button(f"🗨️ {topic}", key=f"bt_{topic}", use_container_width=True, 
                      type="primary" if topic == st.session_state.current_topic else "secondary",
                      on_click=lambda t=topic: setattr(st.session_state, 'current_topic', t))
        with c2:
            with st.popover("⋮"):
                # Pin/Unpin
                if pinned:
                    if st.button("📍 Lepas Pin", key=f"un_{topic}"):
                        st.session_state.pinned_topics.remove(topic); st.rerun()
                else:
                    if st.button("📌 Sematkan", key=f"pi_{topic}"):
                        st.session_state.pinned_topics.append(topic); st.rerun()
                # Rename
                new_n = st.text_input("Ganti Nama:", value=topic, key=f"ren_{topic}")
                if st.button("💾 Save", key=f"sv_{topic}"):
                    if new_n and new_n != topic:
                        st.session_state.chats[new_n] = st.session_state.chats.pop(topic)
                        if topic in st.session_state.pinned_topics:
                            st.session_state.pinned_topics = [new_n if x == topic else x for x in st.session_state.pinned_topics]
                        st.session_state.current_topic = new_n; st.rerun()
                # Delete
                if st.button("🗑️ Hapus", key=f"del_{topic}"):
                    if len(st.session_state.chats) > 1:
                        del st.session_state.chats[topic]
                        if topic in st.session_state.pinned_topics: st.session_state.pinned_topics.remove(topic)
                        st.session_state.current_topic = list(st.session_state.chats.keys())[0]; st.rerun()

    if st.session_state.pinned_topics:
        st.markdown("### 📌 Tersemat")
        for t in st.session_state.pinned_topics: render_topic(t, True)
        st.divider()
    
    st.markdown("### 📚 Riwayat")
    for t in list(st.session_state.chats.keys()):
        if t not in st.session_state.pinned_topics: render_topic(t, False)

# --- 6. CHAT INTERFACE ---
llm = ChatGoogleGenerativeAI(model=sel_model, temperature=0.3)
for m in st.session_state.chats[st.session_state.current_topic]:
    with st.chat_message(m["role"]): st.markdown(m["content"])

if p := st.chat_input("Tanya asisten..."):
    st.session_state.chats[st.session_state.current_topic].append({"role": "user", "content": p})
    with st.chat_message("user"): st.markdown(p)
    with st.chat_message("assistant"):
        with st.spinner("Mikir..."):
            if not os.path.exists("db_ingatan_faiss"): ans = "Sync dulu!"
            else:
                db = FAISS.load_local("db_ingatan_faiss", GoogleGenerativeAIEmbeddings(model="gemini-embedding-001"), allow_dangerous_deserialization=True)
                ctx = "\n\n".join([d.page_content for d in db.similarity_search(p, k=2)])
                resp = llm.invoke(f"Konteks: {ctx}\n\nPertanyaan: {p}")
                if hasattr(resp, 'usage_metadata'):
                    st.session_state.total_tokens_in += resp.usage_metadata.get('prompt_token_count', 0)
                    st.session_state.total_tokens_out += resp.usage_metadata.get('candidates_token_count', 0)
                ans = resp.content[0].get('text', str(resp.content)) if isinstance(resp.content, list) else resp.content
            st.markdown(ans)
            st.session_state.chats[st.session_state.current_topic].append({"role": "assistant", "content": ans})
            st.rerun()