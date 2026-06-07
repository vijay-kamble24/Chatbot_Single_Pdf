import os
import time
import shutil
import unicodedata
import re
from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
import psutil

from config import settings
from database import init_db, get_db, PDFDocument, PDFChunk, get_db_url_for_app_db
from services.pdf_service import enqueue_pdf_ingestion, scan_and_ingest_directory
from services.embedding_service import generate_embeddings_batch
from services.qdrant_service import similarity_search
from services.llm_service import stream_llm_response, validate_llm_provider_config

app = FastAPI(title="Single PDF Chatbot APIs")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory rolling metrics for monitoring
query_times = []

class AskRequest(BaseModel):
    pdf_name: str
    question: str
    chat_history: list[dict] = []

def sanitize_filename(filename: str) -> str:
    """Sanitize the filename to prevent directory traversal and clean special characters."""
    # Strip path
    filename = os.path.basename(filename)
    # Normalize unicode
    filename = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    # Keep alphanumeric, dots, hyphens, and underscores
    filename = re.sub(r"[^\w\.\-_]", "_", filename)
    # Prevent empty name
    if not filename or filename in (".", ".."):
        filename = f"uploaded_{int(time.time())}.pdf"
    return filename

@app.on_event("startup")
def startup_event():
    """Initializes the database and ensures upload directories exist on startup."""
    print("Starting up PDF Chatbot Application...")
    # Initialize SQL Server database and tables
    init_db()
    
    # Ensure data directory and uploads folder exist
    os.makedirs(settings.DATA_DIR, exist_ok=True)
    os.makedirs(os.path.join(settings.DATA_DIR, "uploads"), exist_ok=True)
    
    # Run automatic folder scan on startup in the background
    # We pass the db session maker down (SessionLocal is bound in database.py on init_db)
    from database import _SessionLocal
    if _SessionLocal:
        print("Triggering initial directory scan...")
        scan_and_ingest_directory(settings.DATA_DIR, _SessionLocal)

@app.get("/")
def read_root():
    """Redirect root access to static index.html."""
    return RedirectResponse(url="/static/index.html")

@app.post("/api/pdf/upload")
def upload_pdf(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Receives an uploaded PDF file, validates it, and queues it for ingestion.
    """
    # 1. Validate PDF extension and content type
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed.")
        
    if file.content_type != "application/pdf":
        # Sometimes browsers don't send the content type correctly, so we check extension primarily,
        # but warn if content type is totally wrong and not application/octet-stream
        if file.content_type and "pdf" not in file.content_type:
            raise HTTPException(status_code=400, detail="Uploaded file must be a PDF.")

    # 2. Sanitize filename
    clean_filename = sanitize_filename(file.filename)
    
    # 3. Save to data/uploads
    upload_dir = os.path.join(settings.DATA_DIR, "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, clean_filename)
    
    # Limit file size to 50MB
    MAX_FILE_SIZE = 50 * 1024 * 1024
    size = 0
    try:
        with open(file_path, "wb") as buffer:
            for chunk in file.file:
                size += len(chunk)
                if size > MAX_FILE_SIZE:
                    raise HTTPException(status_code=400, detail="File size exceeds the 50MB limit.")
                buffer.write(chunk)
    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
        
    # 4. Enqueue background ingestion
    from database import _SessionLocal
    enqueue_pdf_ingestion(file_path, "uploads", _SessionLocal)
    
    return {
        "status": "success",
        "message": "PDF uploaded and ingestion scheduled in background.",
        "filename": clean_filename,
        "folder": "uploads"
    }

@app.post("/api/pdf/ingest-folder")
def ingest_folder(background_tasks: BackgroundTasks):
    """
    Scans the configured data directory for new or modified PDFs and ingests them.
    Runs asynchronously in the background.
    """
    from database import _SessionLocal
    if not _SessionLocal:
        raise HTTPException(status_code=500, detail="Database session factory not initialized.")
        
    background_tasks.add_task(scan_and_ingest_directory, settings.DATA_DIR, _SessionLocal)
    return {"status": "success", "message": "Recursive folder scan and ingestion started in background."}

@app.get("/api/pdf/files")
def list_files(db: Session = Depends(get_db)):
    """
    Returns a list of all PDFs currently registered in the database.
    """
    pdfs = db.query(PDFDocument).order_by(PDFDocument.updated_at.desc()).all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "folder_name": p.folder_name,
            "status": p.status,
            "total_chunks": p.total_chunks,
            "error_message": p.error_message,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None
        }
        for p in pdfs
    ]

@app.post("/api/chat/ask")
async def ask_question(request: AskRequest, db: Session = Depends(get_db)):
    """
    Accepts a user question, queries Qdrant for relevant chunks (strictly filtered by PDF),
    and streams the conversational response.
    """
    start_time = time.time()
    
    # 1. Verify PDF document exists in database and is COMPLETED
    pdf_doc = db.query(PDFDocument).filter(PDFDocument.name == request.pdf_name).first()
    if not pdf_doc:
        raise HTTPException(status_code=404, detail=f"PDF document '{request.pdf_name}' not found.")
        
    if pdf_doc.status != "COMPLETED":
        raise HTTPException(
            status_code=400, 
            detail=f"PDF document is not ready yet. Current status: {pdf_doc.status}."
        )
        
    # 2. Generate embedding for user query
    try:
        query_vectors = generate_embeddings_batch([request.question])
        query_vector = query_vectors[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate query embedding: {str(e)}")
        
    # 3. Retrieve relevant chunks from Qdrant, strictly filtered by pdf_name
    try:
        # Retrieve top 4 relevant chunks
        context_chunks = similarity_search(request.pdf_name, query_vector, limit=4)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search vector database: {str(e)}")
        
    try:
        validate_llm_provider_config()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Track search query latency
    query_latency = time.time() - start_time
    global query_times
    query_times.append(query_latency)
    if len(query_times) > 100:
        query_times.pop(0)
        
    # 4. Stream response using SSE
    # stream_llm_response yields "data: {json}\n\n" formatted lines
    # content_type MUST be "text/event-stream"
    generator = stream_llm_response(
        question=request.question,
        pdf_name=request.pdf_name,
        context_chunks=context_chunks,
        chat_history=request.chat_history
    )
    
    return StreamingResponse(generator, media_type="text/event-stream")

@app.get("/api/monitoring/stats")
def get_monitoring_stats(db: Session = Depends(get_db)):
    """
    Gathers metrics for CPU, Memory, Ingestion, and Queries.
    """
    # System Stats
    # interval=None is non-blocking (returns immediate cpu percent since last call)
    cpu_usage = psutil.cpu_percent(interval=None)
    memory_usage = psutil.virtual_memory().percent
    
    # DB Stats
    total_pdfs = db.query(PDFDocument).count()
    completed_pdfs = db.query(PDFDocument).filter(PDFDocument.status == "COMPLETED").count()
    failed_pdfs = db.query(PDFDocument).filter(PDFDocument.status == "FAILED").count()
    processing_pdfs = db.query(PDFDocument).filter(PDFDocument.status == "PROCESSING").count()
    total_chunks = db.query(PDFChunk).count()
    
    # Compute Average Ingestion Time (for completed PDFs)
    ingestion_times = []
    completed_docs = db.query(PDFDocument).filter(PDFDocument.status == "COMPLETED").all()
    for doc in completed_docs:
        if doc.created_at and doc.updated_at:
            duration = (doc.updated_at - doc.created_at).total_seconds()
            ingestion_times.append(duration)
            
    avg_ingestion_time = sum(ingestion_times) / len(ingestion_times) if ingestion_times else 0.0
    
    # Compute Average Query Latency
    avg_query_time = sum(query_times) / len(query_times) if query_times else 0.0
    
    # Config parameters for display
    embedding_info = f"{settings.EMBEDDING_PROVIDER} ({settings.EMBEDDING_MODEL})"

    provider = settings.LLM_PROVIDER.lower()
    llm_model = settings.OPENAI_MODEL
    if provider == "gemini":
        llm_model = settings.GEMINI_MODEL
    elif provider == "azure":
        llm_model = settings.AZURE_OPENAI_DEPLOYMENT
    elif provider == "ollama":
        llm_model = settings.OLLAMA_MODEL
    llm_info = f"{settings.LLM_PROVIDER} ({llm_model})"
    
    return {
        "system": {
            "cpu_percent": cpu_usage,
            "memory_percent": memory_usage,
            "db_connection_url": get_db_url_for_app_db().split("@")[-1]  # expose host/DB only
        },
        "database": {
            "total_documents": total_pdfs,
            "completed_documents": completed_pdfs,
            "processing_documents": processing_pdfs,
            "failed_documents": failed_pdfs,
            "total_chunks": total_chunks
        },
        "performance": {
            "avg_ingestion_seconds": round(avg_ingestion_time, 2),
            "avg_query_seconds": round(avg_query_time, 3),
            "active_workers": settings.MAX_WORKERS
        },
        "configuration": {
            "embedding_provider": embedding_info,
            "llm_provider": llm_info,
            "chunk_size": settings.CHUNK_SIZE,
            "chunk_overlap": settings.CHUNK_OVERLAP
        }
    }

# Mount static folder for frontend (create static folder if it doesn't exist)
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
