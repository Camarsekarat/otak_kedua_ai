import os
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

print("Mencari nama model Teks (LLM) yang diijinin buat API Key lu...\n")
ada_model = False

for m in genai.list_models():
    if 'generateContent' in m.supported_generation_methods:
        print(f"- Ditemukan: {m.name}")
        ada_model = True

if not ada_model:
    print("Waduh, API Key lu nggak dikasih akses buat mikir/nulis teks!")