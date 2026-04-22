import json
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Load kredensial SA lu
with open('service_account.json') as f:
    creds_info = json.load(f)

creds = service_account.Credentials.from_service_account_info(
    creds_info, scopes=['https://www.googleapis.com/auth/drive']
)
service = build('drive', 'v3', credentials=creds)

# 1. Cek Detail Kuota
about = service.about().get(fields="storageQuota").execute()
quota = about['storageQuota']
limit = int(quota['limit']) / (1024**3)
used = int(quota['usage']) / (1024**3)

print(f"📊 DATA KUOTA SERVICE ACCOUNT:")
print(f"Total Limit: {limit:.2f} GB")
print(f"Terpakai   : {used:.2f} GB")
print(f"Sisa       : {(limit - used):.2f} GB")

# 2. Opsional: Bersihkan Trash kalau sudah mepet
if (limit - used) < 1:
    print("\n🧹 Membersihkan Trash...")
    service.files().emptyTrash().execute()
    print("Trash berhasil dikosongkan!")