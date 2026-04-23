import streamlit as st
import os
import json
import io
import requests
import datetime
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS

# --- 1. PAGE CONFIG & PREMIUM UI ---
st.set_page_config(page_title="Otak Kedua v5.2", page_icon="🧠", layout="wide")

st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {background-color: transparent !important;}
    [data-testid="stHeader"] {background-color: transparent !important;}
    
    .block-container {
        max-width: 800px !important;
        padding-top: 1rem !important;
    }

    [data-testid="stChatMessage"]:has([alt="user avatar"]) {
        background-color: #1e1f22; 
        border-radius: 20px 20px 5px 20px;
        padding: 12px 18px;
        margin-bottom: 20px;
        border: 1px solid #2d3036;
    }

    [data-testid="stChatMessage"]:has([alt="assistant avatar"]) {
        background-color: transparent;
        padding: 10px 0;
        margin-bottom: 20px;
    }

    [data-testid="stSidebar"] {
        background-color: #131314 !important;
        border-right: 1px solid #282a2c !important;
    }
    [data-testid="stSidebar"] .css-17lntkn {
        font-family: 'Inter', sans-serif;
    }
    
    div[data-testid="stExpander"] {
        background-color: #1e1f22 !important;
        border: 1px solid #282a2c !important;
        border-radius: 10px !important;
        overflow: hidden;
    }
    div[data-testid="stExpander"] summary {
        background-color: transparent !important;
        padding: 12px !important;
    }
    
    .stButton > button {
        border-radius: 8px !important;
        border: 1px solid #3c4456 !important;
        transition: all 0.3s ease;
    }
    .stButton > button:hover {
        border-color: #63b3ed !important;
        box-shadow: 0 0 10px rgba(99, 179, 237, 0.2);
    }
</style>
""", unsafe_allow_html=True)

# --- 2. KONFIGURASI API ---
try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
    FOLDER_ID = st.secrets["GDRIVE_FOLDER_ID"]
    creds_info = json.loads(st.secrets["SERVICE_ACCOUNT_JSON"])
    genai.configure(api_key=API_KEY)
    os.environ["GOOGLE_API_KEY"] = API_KEY
    SCOPES = ['https://www.googleapis.com/auth/drive']
except Exception as e:
    st.error(f"Error Secrets: {e}")
    st.stop()

# --- 3. DATABASE LOKAL & SESSION STATE ---
DB_FILE = "app_database.json"

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return {"chats": {"Chat Utama": []}, "billing": {}}

def save_db():
    data = {
        "chats": st.session_state.chats,
        "billing": st.session_state.billing
    }
    with open(DB_FILE, "w") as f:
        json.dump(data, f)

db_data = load_db()
if "chats" not in st.session_state: st.session_state.chats = db_data["chats"]
if "billing" not in st.session_state: st.session_state.billing = db_data["billing"]
if "current_topic" not in st.session_state: st.session_state.current_topic = list(st.session_state.chats.keys())[0]
if "file_list" not in st.session_state: st.session_state.file_list = []
if "kurs_idr" not in st.session_state: st.session_state.kurs_idr = 16000.0

# --- 4. BACKEND FUNCTIONS ---
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
    except: pass

def sync_data():
    service = get_drive_service()
    fetch_files()
    docs = []
    for f in st.session_state.file_list:
        t = service.files().export_media(fileId=f['id'], mimeType='text/plain').execute().decode('utf-8')
        docs.append(Document(page_content=t, metadata={"source": f['name']}))
    if docs:
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        chunks = splitter.split_documents(docs)
        embeddings = GoogleGenerativeAIEmbeddings(model="gemini-embedding-001", google_api_key=API_KEY)
        FAISS.from_documents(chunks, embeddings).save_local("db_ingatan_faiss")

def simpan_atau_update_memori(file_selection, isi):
    try:
        service = get_drive_service()
        f_id = next(f['id'] for f in st.session_state.file_list if f['name'] == file_selection)
        old_content = service.files().export_media(fileId=f_id, mimeType='text/plain').execute().decode('utf-8')
        new_text = old_content + "\n\n---\nUpdate:\n" + isi
        media = MediaIoBaseUpload(io.BytesIO(new_text.encode('utf-8')), mimetype='text/plain', resumable=False)
        service.files().update(fileId=f_id, media_body=media, supportsAllDrives=True).execute()
        sync_data()
        return True, "Suntikan berhasil & Auto-Sync selesai!"
    except Exception as e:
        return False, str(e)

def hitung_biaya(tokens_in, tokens_out):
    st.session_state.kurs_idr = fetch_realtime_kurs()
    p_in = (0.075/1e6) * st.session_state.kurs_idr
    p_out = (0.30/1e6) * st.session_state.kurs_idr
    return (tokens_in * p_in) + (tokens_out * p_out)

# --- 5. SISTEM LOGIN (AUTO-SYNC AMAN) ---
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.markdown("<h2 style='text-align: center;'>🔒 Login Otak Kedua</h2>", unsafe_allow_html=True)
        inp_user = st.text_input("Username")
        inp_pass = st.text_input("Password", type="password")
        if st.button("Masuk", use_container_width=True):
            try:
                if inp_user == st.secrets["APP_USER"] and inp_pass == st.secrets["APP_PASS"]:
                    st.session_state.logged_in = True
                    # Auto-Sync setelah sukses login
                    with st.spinner("Sinkronisasi memori awal dari G-Drive..."):
                        sync_data()
                    st.rerun() 
                else:
                    st.error("❌ Username atau Password salah!")
            except KeyError:
                st.error("Tambahin APP_USER dan APP_PASS di Streamlit Secrets!")
            except Exception as e:
                st.error(f"Error sistem: {e}")
    st.stop()

# --- 6. UI SIDEBAR ---
with st.sidebar:
    st.markdown("<h1 style='text-align: center;'>🧠</h1>", unsafe_allow_html=True)
    if st.button("➕ Chat Baru", use_container_width=True):
        new_id = f"Chat {len(st.session_state.chats) + 1}"
        st.session_state.chats[new_id] = []
        st.session_state.current_topic = new_id
        save_db()
        st.rerun()
    st.divider()

    with st.expander("📝 Suntik & Sistem AI", expanded=False):
        fetch_files()
        opts = [f['name'] for f in st.session_state.file_list]
        if opts:
            sel_file = st.selectbox("Target Catatan", opts)
            isi_memori = st.text_area("Isi Tambahan", height=100)
            if st.button("🚀 Suntik & Auto-Sync", use_container_width=True):
                if isi_memori:
                    with st.spinner("Menyuntik..."):
                        ok, msg = simpan_atau_update_memori(sel_file, isi_memori)
                        if ok: st.success(msg)
                        else: st.error(msg)
        st.divider()
        sel_model = st.selectbox("Otak AI", ["gemini-2.5-flash", "gemini-2.5-pro"])
        
        st.divider()
        st.markdown("**🛡️ Pengaman Data**")
        if st.button("💾 Backup DB ke G-Drive", use_container_width=True):
            with st.spinner("Mengamankan..."):
                try:
                    with open(DB_FILE, "r") as f:
                        db_content = f.read()
                    service = get_drive_service()
                    q = f"'{FOLDER_ID}' in parents and name='backup_otak_kedua.json' and trashed=false"
                    existing_files = service.files().list(q=q, fields="files(id)").execute().get('files', [])
                    media = MediaIoBaseUpload(io.BytesIO(db_content.encode('utf-8')), mimetype='application/json', resumable=False)
                    if existing_files:
                        service.files().update(fileId=existing_files[0]['id'], media_body=media).execute()
                    else:
                        file_metadata = {'name': 'backup_otak_kedua.json', 'parents': [FOLDER_ID]}
                        service.files().create(body=file_metadata, media_body=media).execute()
                    st.success("✅ Database aman di G-Drive!")
                except Exception as e:
                    st.error(f"Gagal backup: {e}")

    with st.expander("📊 Laporan Billing", expanded=False):
        today_str = datetime.date.today().isoformat()
        t_in_hari_ini = st.session_state.billing.get(today_str, {}).get("in", 0)
        t_out_hari_ini = st.session_state.billing.get(today_str, {}).get("out", 0)
        t_in_total = sum(d.get("in", 0) for d in st.session_state.billing.values())
        t_out_total = sum(d.get("out", 0) for d in st.session_state.billing.values())
        
        st.markdown("**Hari Ini:**")
        st.metric("Rupiah", f"Rp {hitung_biaya(t_in_hari_ini, t_out_hari_ini):,.2f}")
        st.markdown("**Total Keseluruhan:**")
        st.metric("Rupiah", f"Rp {hitung_biaya(t_in_total, t_out_total):,.2f}")

    st.divider()
    st.markdown("### Riwayat Chat")
    for t in list(st.session_state.chats.keys()):
        col1, col2 = st.columns([0.8, 0.2])
        with col1:
            if st.button(f"🗨️ {t}", key=f"t_{t}", use_container_width=True, type="primary" if t == st.session_state.current_topic else "secondary"):
                st.session_state.current_topic = t
                st.rerun()
        with col2:
            if st.button("🗑️", key=f"del_{t}"):
                if len(st.session_state.chats) > 1:
                    del st.session_state.chats[t]
                    st.session_state.current_topic = list(st.session_state.chats.keys())[0]
                    save_db()
                    st.rerun()

# --- 7. MAIN CHAT LOGIC (HYBRID PROMPT) ---
st.title(f"🧠 {st.session_state.current_topic}")

llm = ChatGoogleGenerativeAI(model=sel_model, google_api_key=API_KEY, temperature=0.3)

for m in st.session_state.chats[st.session_state.current_topic]:
    with st.chat_message(m["role"], avatar="🧑‍💻" if m["role"] == "user" else "✨"): 
        st.markdown(m["content"])
        if "sumber" in m and m["sumber"]:
            with st.expander("🔍 Intip Sumber Data"):
                st.markdown(m["sumber"])

if p := st.chat_input("Tanya soal isi memori lu..."):
    st.session_state.chats[st.session_state.current_topic].append({"role": "user", "content": p})
    with st.chat_message("user", avatar="🧑‍💻"): 
        st.markdown(p)
    save_db()

    with st.chat_message("assistant", avatar="✨"):
        if not os.path.exists("db_ingatan_faiss"):
            st.error("Database memori kosong, Bre! Suntik data dulu di Menu Samping.")
        else:
            try:
                db = FAISS.load_local("db_ingatan_faiss", GoogleGenerativeAIEmbeddings(model="gemini-embedding-001", google_api_key=API_KEY), allow_dangerous_deserialization=True)
                res = db.similarity_search(p, k=3)
                
                kumpulan_teks = []
                teks_sumber = "**Data yang dibaca AI:**\n\n"
                for doc in res:
                    kumpulan_teks.append(doc.page_content)
                    # Menampilkan ujung kalimat (fix [-150:])
                    teks_sumber += f"📄 **{doc.metadata.get('source', 'Unknown')}**\n> ...{doc.page_content[-150:]}\n\n"
                context_gabungan = "\n\n---\n\n".join(kumpulan_teks)
                
                # PROMPT HYBRID: Pintar baca data, bisa jawab pengetahuan umum
                prompt_final = f"""Lu adalah asisten Otak Kedua. 
Tugas utama lu: Jawab pertanyaan user.

1. CEK KONTEKS G-DRIVE di bawah ini. Jika ada informasi yang relevan, utamakan jawaban dari konteks tersebut.
2. JIKA DI KONTEKS TIDAK ADA (misal nanya saran, opini, atau trik umum), LU BOLEH JAWAB menggunakan pengetahuan umum AI lu. 
Namun, awali jawaban lu dengan kalimat: "Di ingatan G-Drive lu belum ada spesifik soal ini Bre, tapi menurut gue..."

KONTEKS G-DRIVE:
{context_gabungan}

PERTANYAAN USER: {p}
"""
                with st.expander("🔍 Intip Sumber Data"):
                    st.markdown(teks_sumber)

                response_placeholder = st.empty()
                full_answer = ""
                
                for chunk in llm.stream(prompt_final):
                    full_answer += chunk.content
                    response_placeholder.markdown(full_answer + " ▌") 
                
                response_placeholder.markdown(full_answer)
                
                st.session_state.chats[st.session_state.current_topic].append({
                    "role": "assistant", 
                    "content": full_answer,
                    "sumber": teks_sumber
                })
                
                today_str = datetime.date.today().isoformat()
                if today_str not in st.session_state.billing:
                    st.session_state.billing[today_str] = {"in": 0, "out": 0}
                
                st.session_state.billing[today_str]["in"] += len(prompt_final.split()) * 1.3
                st.session_state.billing[today_str]["out"] += len(full_answer.split()) * 1.3
                save_db() 

            except Exception as e:
                st.error(f"Error dari mesin AI: {e}")