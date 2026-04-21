import streamlit as st
import os
import yaml
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth
from datetime import datetime
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS

# --- 1. CONFIG & SETUP ---
st.set_page_config(page_title="Otak Kedua v8.0", layout="wide")

# --- 2. SISTEM LOGIN (AUTHENTICATOR) ---
# Baca database user dari config.yaml
try:
    with open('config.yaml', 'r', encoding='utf-8') as file:
        config = yaml.load(file, Loader=SafeLoader)
except FileNotFoundError:
    st.error("Woi Bre, file config.yaml belum lu bikin!")
    st.stop()

# Nyalain mesin autentikasi
authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days'],
    config['preauthorized']
)

# Render UI Form Login di tengah layar
authenticator.login()

# --- 3. GERBANG KEAMANAN ---
if st.session_state.get("authentication_status"):
    # KALAU LOGIN BERHASIL, JALANKAN SEMUA APLIKASI DI BAWAH INI
    
    # Tombol Logout di Sidebar
    authenticator.logout('Keluar (Logout)', 'sidebar')
    st.sidebar.write(f"Selamat datang, **{st.session_state['name']}** 🛡️")
    st.sidebar.divider()

    # --- KODINGAN OTAK KEDUA V7.0 DIMULAI DARI SINI ---
    FOLDER_MEMORI = "memori_offline"
    DB_PATH = "db_offline"
    FILE_CHAT_LOG = os.path.join(FOLDER_MEMORI, "Auto_Riwayat_Chat.txt")

    if not os.path.exists(FOLDER_MEMORI): os.makedirs(FOLDER_MEMORI)

    try:
        API_KEY = st.secrets["GOOGLE_API_KEY"]
    except:
        st.error("API Key gak ketemu di .streamlit/secrets.toml!")
        st.stop()

    @st.cache_resource
    def get_local_embeddings():
        return HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

    local_embeddings = get_local_embeddings()

    def sync_memori_lokal():
        files = [f for f in os.listdir(FOLDER_MEMORI) if f.endswith(".txt")]
        if not files: return False, "Folder memori kosong!"
        
        docs = []
        for f in files:
            path = os.path.join(FOLDER_MEMORI, f)
            with open(path, "r", encoding="utf-8") as file:
                docs.append(Document(page_content=file.read(), metadata={"source": f}))
        
        try:
            with st.status("⚙️ Menghitung Vektor di Laptop...", expanded=True) as status:
                splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
                chunks = splitter.split_documents(docs)
                vector_db = FAISS.from_documents(chunks, local_embeddings)
                vector_db.save_local(DB_PATH)
                status.update(label="✅ Berhasil Sync!", state="complete", expanded=False)
            return True, len(chunks)
        except Exception as e:
            return False, str(e)

    def simpan_riwayat_chat(role, teks):
        waktu = datetime.now().strftime("%Y-%m-%d %H:%M")
        label = "[USER]" if role == "user" else "[MODEL]"
        with open(FILE_CHAT_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n{waktu} | {label}: {teks}\n")

    # --- UI SIDEBAR MEMORI ---
    with st.sidebar:
        st.header("📄 Input Memori")
        
        list_catatan = [f.replace(".txt", "") for f in os.listdir(FOLDER_MEMORI) if f.endswith(".txt") and f != "Auto_Riwayat_Chat.txt"]
        pilihan_target = ["➕ Buat Catatan Baru"] + list_catatan
        target = st.selectbox("Pilih Target Catatan", pilihan_target)
        
        if target == "➕ Buat Catatan Baru":
            nama_file = st.text_input("Nama File Baru")
        else:
            nama_file = target
            
        isi_catatan = st.text_area("Isi Catatan", height=150)
        
        if st.button("🚀 Simpan ke Drive (Lokal)", use_container_width=True):
            if nama_file and isi_catatan:
                path_file = os.path.join(FOLDER_MEMORI, f"{nama_file}.txt")
                with open(path_file, "a", encoding="utf-8") as f:
                    f.write(f"\n\n--- Catatan Baru ---\n{isi_catatan}")
                st.success(f"Tersimpan di {nama_file}!")
            else:
                st.warning("Nama dan isi jangan kosong, Bre!")
                
        st.divider()
        if st.button("🔄 Sync Semua Memori", use_container_width=True):
            ok, msg = sync_memori_lokal()
            if ok: st.toast(f"Berhasil serap {msg} potongan memori!")

    # --- CHAT ENGINE MAIN AREA ---
    col1, col2 = st.columns([0.8, 0.2])
    with col1: st.title("🧠 Otak Kedua")
    with col2: 
        if st.button("🗑️ Clear Layar"): st.session_state.chats = []

    if "chats" not in st.session_state: st.session_state.chats = []

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash", 
        google_api_key=API_KEY,
        temperature=0.3
    )

    for m in st.session_state.chats:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    if p := st.chat_input("Tanya asisten..."):
        st.session_state.chats.append({"role": "user", "content": p})
        simpan_riwayat_chat("user", p)
        
        with st.chat_message("user"): st.markdown(p)

        with st.chat_message("assistant"):
            if not os.path.exists(DB_PATH):
                st.warning("Database belum ada. Simpan catatan dan klik Sync dulu!")
            else:
                try:
                    db = FAISS.load_local(DB_PATH, local_embeddings, allow_dangerous_deserialization=True)
                    res = db.similarity_search(p, k=4)
                    ctx = "\n\n".join([f"Sumber ({d.metadata['source']}):\n{d.page_content}" for d in res])
                    
                    full_prompt = f"""Konteks: {ctx}\n\nPertanyaan: {p}"""
                    response = llm.invoke(full_prompt)
                    ans = response.content
                    
                    st.markdown(ans)
                    st.session_state.chats.append({"role": "assistant", "content": ans})
                    simpan_riwayat_chat("model", ans)
                except Exception as e:
                    st.error(f"Error: {e}")

# --- 4. LOGIKA JIKA GAGAL LOGIN ---
elif st.session_state.get("authentication_status") is False:
    st.error("❌ Username atau Password salah, Bre!")
elif st.session_state.get("authentication_status") is None:
    st.warning("🔒 Silakan masukin kredensial lu buat buka Otak Kedua.")