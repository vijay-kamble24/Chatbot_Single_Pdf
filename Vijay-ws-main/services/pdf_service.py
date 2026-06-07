import os
import hashlib
import uuid
import datetime
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy.orm import Session
from pypdf import PdfReader

from config import settings
from database import PDFDocument, PDFChunk
# We will import qdrant_service and embedding_service inside the function or locally 
# to avoid circular imports.

# ThreadPoolExecutor to run ingestion in the background with limited workers (CPU optimization)
ingestion_executor = ThreadPoolExecutor(max_workers=settings.MAX_WORKERS, thread_name_prefix="pdf_ingest_")

# A set of currently processing file paths to avoid double-processing the same file in parallel
processing_files = set()

def calculate_checksum(file_path: str) -> str:
    """Calculate SHA256 checksum of a file to check for modifications."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256.update(byte_block)
    return sha256.hexdigest()

def chunk_text(text: str, page_num: int, chunk_size_tokens: int = 600, overlap_tokens: int = 80):
    """
    Splits text into chunks of roughly 500-800 tokens with 50-100 tokens overlap.
    We approximate 1 token = 4 characters.
    """
    chunk_size = chunk_size_tokens * 4
    overlap = overlap_tokens * 4
    
    chunks = []
    if not text or len(text.strip()) == 0:
        return chunks
        
    start = 0
    text_len = len(text)
    
    while start < text_len:
        end = start + chunk_size
        chunk_content = text[start:end]
        
        # Avoid splitting words at the end of the chunk if there's more text
        if end < text_len:
            # Look back up to 150 characters for a word boundary (space or newline)
            boundary = max(start, end - 150)
            space_idx = text.rfind(" ", boundary, end)
            newline_idx = text.rfind("\n", boundary, end)
            
            split_idx = max(space_idx, newline_idx)
            if split_idx > start:
                end = split_idx
                chunk_content = text[start:end]
        
        chunk_text_clean = chunk_content.strip()
        if chunk_text_clean:
            # Generate a hash for this specific chunk text to avoid duplicates
            chunk_hash = hashlib.sha256(chunk_text_clean.encode("utf-8")).hexdigest()
            chunks.append({
                "text": chunk_text_clean,
                "page": page_num,
                "checksum": chunk_hash
            })
            
        start += (end - start) - overlap
        if start >= text_len or (end - start) <= 0:
            break
            
    return chunks

def process_pdf_file(file_path: str, folder_name: str, db: Session):
    """
    Synchronous processing of a single PDF file:
    1. Extracts text page-by-page.
    2. Generates chunks.
    3. Saves chunk metadata to SQL database.
    4. Generates embeddings.
    5. Saves vectors to Qdrant.
    """
    # Import services here to prevent circular dependency
    from services.embedding_service import generate_embeddings_batch
    from services.qdrant_service import store_vectors, delete_vectors_by_pdf_name

    file_name = os.path.basename(file_path)
    print(f"[{datetime.datetime.now()}] Starting ingestion for {file_name}...")
    
    try:
        # Calculate checksum
        checksum = calculate_checksum(file_path)
        
        # Check if PDF exists in DB
        pdf_doc = db.query(PDFDocument).filter(PDFDocument.file_path == file_path).first()
        
        if pdf_doc:
            # If it exists and status is COMPLETED and checksum is identical, skip!
            if pdf_doc.checksum == checksum and pdf_doc.status == "COMPLETED":
                print(f"[{datetime.datetime.now()}] PDF {file_name} is already processed and unmodified. Skipping.")
                return
            
            # If modified or failed, we clear old database chunks and vector database points
            print(f"[{datetime.datetime.now()}] Re-processing modified or incomplete PDF: {file_name}")
            pdf_doc.status = "PROCESSING"
            pdf_doc.checksum = checksum
            pdf_doc.error_message = None
            db.commit()
            
            # Clean up old vectors and DB chunks
            delete_vectors_by_pdf_name(file_name)
            db.query(PDFChunk).filter(PDFChunk.pdf_id == pdf_doc.id).delete()
            db.commit()
        else:
            # Create new PDFDocument entry
            pdf_doc = PDFDocument(
                name=file_name,
                folder_name=folder_name,
                file_path=file_path,
                checksum=checksum,
                status="PROCESSING"
            )
            db.add(pdf_doc)
            db.commit()
            db.refresh(pdf_doc)
            
        # Parse PDF using pypdf
        reader = PdfReader(file_path)
        all_chunks = []
        
        for page_idx, page in enumerate(reader.pages):
            page_text = page.extract_text()
            page_chunks = chunk_text(page_text, page_idx + 1, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP)
            all_chunks.extend(page_chunks)
            
        if not all_chunks:
            raise ValueError("No extractable text found in this PDF document.")
            
        print(f"[{datetime.datetime.now()}] Extracted {len(all_chunks)} chunks from {file_name}. Storing in SQL Server...")
        
        # Store Chunk metadata in SQL Server
        db_chunks = []
        for idx, chunk in enumerate(all_chunks):
            chunk_id = str(uuid.uuid4())
            db_chunk = PDFChunk(
                id=chunk_id,
                pdf_id=pdf_doc.id,
                pdf_name=file_name,
                folder_name=folder_name,
                chunk_index=idx,
                page_number=chunk["page"],
                chunk_text=chunk["text"],
                embedding_status="PENDING",
                checksum=chunk["checksum"]
            )
            db.add(db_chunk)
            db_chunks.append(db_chunk)
            
        pdf_doc.total_chunks = len(db_chunks)
        db.commit()
        
        # Generate embeddings in batches (CPU optimization)
        print(f"[{datetime.datetime.now()}] Generating embeddings for {file_name}...")
        texts = [c.chunk_text for c in db_chunks]
        embeddings = generate_embeddings_batch(texts)
        
        if len(embeddings) != len(db_chunks):
            raise ValueError(f"Embedding count mismatch. Expected {len(db_chunks)}, got {len(embeddings)}.")
            
        # Store in Qdrant
        print(f"[{datetime.datetime.now()}] Saving embeddings to Qdrant for {file_name}...")
        payloads = [
            {
                "chunk_id": c.id,
                "pdf_id": pdf_doc.id,
                "pdf_name": file_name,
                "folder_name": folder_name,
                "page_number": c.page_number,
                "text": c.chunk_text
            }
            for c in db_chunks
        ]
        ids = [c.id for c in db_chunks]
        
        # Store vectors in Qdrant
        store_vectors(ids, embeddings, payloads)
        
        # Update status in DB
        for db_chunk in db_chunks:
            db_chunk.embedding_status = "COMPLETED"
        pdf_doc.status = "COMPLETED"
        db.commit()
        print(f"[{datetime.datetime.now()}] Ingestion completed successfully for {file_name}.")
        
    except Exception as e:
        print(f"[{datetime.datetime.now()}] Ingestion failed for {file_name}: {str(e)}")
        db.rollback()
        # Reload doc context to update error status
        try:
            pdf_doc = db.query(PDFDocument).filter(PDFDocument.file_path == file_path).first()
            if pdf_doc:
                pdf_doc.status = "FAILED"
                pdf_doc.error_message = str(e)[:2000]
                db.commit()
        except Exception as db_err:
            print(f"Failed to record failure state to DB: {db_err}")
    finally:
        # Release lock
        processing_files.discard(file_path)

def enqueue_pdf_ingestion(file_path: str, folder_name: str, db_session_factory):
    """Add a PDF file to the background ThreadPoolExecutor."""
    if file_path in processing_files:
        print(f"File {file_path} is already in the ingestion queue. Skipping duplicate request.")
        return
        
    processing_files.add(file_path)
    
    # We must create a new DB session inside the background thread to avoid connection sharing
    def run_with_fresh_session():
        db = db_session_factory()
        try:
            process_pdf_file(file_path, folder_name, db)
        finally:
            db.close()
            
    ingestion_executor.submit(run_with_fresh_session)

def scan_and_ingest_directory(directory_path: str, db_session_factory):
    """
    Recursively scans the directory for PDFs.
    Matches folder structures (e.g. data/finance/report.pdf -> folder_name: "finance").
    Schedules ingestion for any new or modified file.
    """
    if not os.path.exists(directory_path):
        os.makedirs(directory_path, exist_ok=True)
        print(f"Created data directory: {directory_path}")
        return
        
    db = db_session_factory()
    try:
        # Base folder paths
        abs_base_dir = os.path.abspath(directory_path)
        
        for root, _, files in os.walk(directory_path):
            for file in files:
                if file.lower().endswith(".pdf"):
                    full_path = os.path.abspath(os.path.join(root, file))
                    
                    # Compute relative folder name (e.g., "finance" for data/finance/report.pdf)
                    rel_path = os.path.relpath(full_path, abs_base_dir)
                    dir_parts = os.path.dirname(rel_path).split(os.sep)
                    folder_name = dir_parts[0] if dir_parts and dir_parts[0] != "" else "root"
                    
                    # Enqueue this file
                    enqueue_pdf_ingestion(full_path, folder_name, db_session_factory)
    finally:
        db.close()
