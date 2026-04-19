import os
from dotenv import load_dotenv
from langchain_google_community import GoogleDriveLoader

load_dotenv()
FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID")

print(f"Mencoba akses folder ID: {FOLDER_ID}")

try:
    loader = GoogleDriveLoader(
        folder_id=FOLDER_ID, 
        service_account_key="credentials.json"
    )
    docs = loader.load()
    
    print(f"Hasil: Ditemukan {len(docs)} dokumen.")
    if len(docs) > 0:
        for i, doc in enumerate(docs):
            print(f"Dokumen {i+1}: {doc.metadata.get('title', 'Tanpa Judul')}")
    else:
        print("ZONK! Robot lu nggak liat file apa-apa. Cek izin share atau tipe filenya!")
except Exception as e:
    print(f"Error: {str(e)}")