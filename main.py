import os
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel

# AI & Embeddings
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Bypass Google Drive & Parser
from langchain_core.documents import Document
from google.oauth2 import service_account
from googleapiclient.discovery import build

# VECTOR DB BARU KITA: FAISS
from langchain_community.vectorstores import FAISS

load_dotenv()

# Setup Otomatis credentials.json
creds_json = os.getenv("GDRIVE_CREDENTIALS_JSON")
if creds_json and not os.path.exists("credentials.json"):
    with open("credentials.json", "w") as f:
        f.write(creds_json)

os.environ["GOOGLE_API_KEY"] = os.getenv("GOOGLE_API_KEY")
FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID")

# Inisialisasi Model
embeddings = GoogleGenerativeAIEmbeddings(model="gemini-embedding-001")
llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-image-preview", temperature=0.3)

# Folder Database
db_path = "./db_ingatan_faiss"

app = FastAPI()

class ChatRequest(BaseModel):
    pesan: str

@app.get("/")
def home():
    return {"status": "Online", "message": "Siap tempur dengan FAISS, Bre!"}

@app.post("/sync")
def sync():
    try:
        # 1. Buka jalur pake mesin asli Google
        creds = service_account.Credentials.from_service_account_file(
            "credentials.json", scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
        service = build('drive', 'v3', credentials=creds)
        
        # 2. Cari file di folder
        query = f"'{FOLDER_ID}' in parents and trashed=false"
        results = service.files().list(q=query, fields="files(id, name, mimeType)").execute()
        items = results.get('files', [])
        
        if not items:
            return {"status": "error", "message": "Foldernya kosong beneran, Bre!"}
            
        docs = []
        # 3. Sedot teksnya satu-satu
        for item in items:
            if item['mimeType'] == 'application/vnd.google-apps.document':
                request = service.files().export_media(fileId=item['id'], mimeType='text/plain')
                teks_mentah = request.execute().decode('utf-8')
                
                if len(teks_mentah.strip()) > 0:
                    docs.append(Document(page_content=teks_mentah, metadata={"source": item['name']}))
        
        if len(docs) == 0:
             return {"status": "error", "message": "File ada, tapi teksnya gagal disedot."}

        # 4. Potong dan Simpan ke FAISS
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        chunks = splitter.split_documents(docs)
        
        vectorstore = FAISS.from_documents(chunks, embeddings)
        vectorstore.save_local(db_path) # Simpan ke hardisk
        
        return {"status": "success", "data": len(chunks)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/tanya")
def tanya(request: ChatRequest):
    try:
        # Load ingatan dari FAISS
        db = FAISS.load_local(db_path, embeddings, allow_dangerous_deserialization=True)
        results = db.similarity_search(request.pesan, k=3)
        
        context = "\n\n".join([d.page_content for d in results])
        prompt = f"Gunakan konteks ini untuk menjawab: {context}\n\n Pertanyaan: {request.pesan}"
        
        response = llm.invoke(prompt)
        return {"jawaban": response.content}
    except Exception as e:
        return {"error": str(e)}