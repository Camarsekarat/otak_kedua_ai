import streamlit as st
import requests

# Set judul aplikasi
st.set_page_config(page_title="Otak Kedua Irfanka", page_icon="🧠")
st.title("🧠 Otak Kedua AI")
st.markdown("---")

# Sidebar buat tombol Sync
with st.sidebar:
    st.header("Kontrol Data")
    if st.button("🔄 Sync G-Drive"):
        with st.spinner("Lagi baca G-Docs lu..."):
            try:
                res = requests.post("http://127.0.0.1:8000/sync")
                if res.status_code == 200:
                    st.success(f"Berhasil! {res.json().get('data')} potongan data masuk memori.")
                else:
                    st.error("Gagal Sync nih, Bre.")
            except:
                st.error("FastAPI-nya udah lu nyalain belom?")

# Inisialisasi chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Nampilin chat lama
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Input Chat
if prompt := st.chat_input("Tanya apa hari ini?"):
    # Nampilin chat user
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Nampilin jawaban AI
    with st.chat_message("assistant"):
        with st.spinner("Mikir sebentar..."):
            try:
                res = requests.post("http://127.0.0.1:8000/tanya", json={"pesan": prompt})
                # Ambil teks dari struktur JSON Gemini lu yang unik tadi
                jawaban_raw = res.json().get("jawaban")
                
                # Handling kalau jawaban bentuknya list (kayak hasil lu tadi)
                if isinstance(jawaban_raw, list):
                    jawaban = jawaban_raw[0].get("text")
                else:
                    jawaban = jawaban_raw

                st.markdown(jawaban)
                st.session_state.messages.append({"role": "assistant", "content": jawaban})
            except Exception as e:
                st.error(f"Error: {e}")