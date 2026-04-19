import os
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_community.document_loaders import GoogleDriveLoader
from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter # Update Import di sini

load_dotenv()

# Setup Otomatis credentials.json
creds_json = os.getenv("GDRIVE_CREDENTIALS_JSON")
if creds_json and not os.path.exists("credentials.json"):
    with open("credentials.json", "w") as f:
        f.write(creds_json)

os.environ["GOOGLE_API_KEY"] = os.getenv("GOOGLE_API_KEY")
FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID")

embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0.3)
db_path = "./db_ingatan"

app = FastAPI()

class ChatRequest(BaseModel):
    pesan: str

@app.get("/")
def home():
    return {"status": "Online", "message": "Siap tempur, Bre!"}

@app.post("/sync")
def sync():
    try:
        loader = GoogleDriveLoader(folder_id=FOLDER_ID, credentials_path="credentials.json")
        docs = loader.load()
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        chunks = splitter.split_documents(docs)
        vectorstore = Chroma.from_documents(documents=chunks, embedding=embeddings, persist_directory=db_path)
        return {"status": "success", "data": len(chunks)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/tanya")
def tanya(request: ChatRequest):
    try:
        db = Chroma(persist_directory=db_path, embedding_function=embeddings)
        results = db.similarity_search(request.pesan, k=3)
        context = "\n\n".join([d.page_content for d in results])
        prompt = f"Gunakan konteks ini untuk menjawab: {context}\n\n Pertanyaan: {request.pesan}"
        response = llm.invoke(prompt)
        return {"jawaban": response.content}
    except Exception as e:
        return {"error": str(e)}