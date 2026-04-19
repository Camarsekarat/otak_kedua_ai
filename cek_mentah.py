import os
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build

load_dotenv()
FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID")
CREDS_FILE = "credentials.json"

print("Mengecek isi folder langsung pake kacamata tembus pandang...\n")

try:
    # Bikin kunci masuk
    creds = service_account.Credentials.from_service_account_file(
        CREDS_FILE, scopes=['https://www.googleapis.com/auth/drive.readonly']
    )
    service = build('drive', 'v3', credentials=creds)

    # Cari SEMUA file di dalam folder tanpa filter
    query = f"'{FOLDER_ID}' in parents and trashed=false"
    results = service.files().list(q=query, fields="files(id, name, mimeType)").execute()
    items = results.get('files', [])

    if not items:
        print("FIX ZONK! Foldernya beneran kosong atau robot belum di-share ke folder ini.")
    else:
        print(f"Ketemu {len(items)} file nih, Bre:")
        for item in items:
            print(f"- Nama: {item['name']}")
            print(f"  Tipe Asli (MimeType): {item['mimeType']}\n")

except Exception as e:
    print(f"Error: {e}")