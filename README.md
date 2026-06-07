**Screenshots**

Upload a single Pdf

<img width="1912" height="1074" alt="image" src="https://github.com/user-attachments/assets/ba3a823f-944d-4b3f-b85f-865532fd9eca" />
You can upload the pdf and after that you have to select that particular pdf to ask the question and get the related information.

<img width="1910" height="1071" alt="image" src="https://github.com/user-attachments/assets/b99a648f-f240-4c18-8152-b096ea4a39e3" />

UI Quadrant/ Vector DB
<img width="1901" height="1083" alt="image" src="https://github.com/user-attachments/assets/e72592a6-b174-474c-8f32-7706df1237cf" />

FastAPI UI

<img width="1919" height="1068" alt="image" src="https://github.com/user-attachments/assets/0842d259-46d7-4b33-92a6-53960c0f7b60" />






# Single PDF Chatbot

A single-document PDF conversational assistant built with FastAPI, Microsoft SQL Server, Qdrant, and Ollama/OpenAI-compatible LLMs. The application ingests PDFs, generates embeddings, stores vectors in Qdrant, and streams chat answers grounded strictly in the selected document.

## Features

- Upload or scan local PDF files
- Deduplicates files using SHA256 checksum
- Extracts text and creates overlapping chunks for document grounding
- Stores metadata in SQL Server and embeddings in Qdrant
- Supports multiple LLM providers: OpenAI, Gemini, Azure, and local Ollama
- Streams chat responses in real time via SSE (`text/event-stream`)
- Provides monitoring stats for CPU, memory, ingestion, and query latency

## Tech Stack

- Python + FastAPI
- Microsoft SQL Server via `pymssql`
- Qdrant vector database
- SQLAlchemy ORM
- FastEmbed local embeddings + optional cloud embeddings
- Server-Sent Events streaming
- Vanilla HTML/CSS/JavaScript frontend

## Repository Structure

- `main.py` - FastAPI application and API route definitions
- `config.py` - Application configuration loaded from `.env`
- `database.py` - SQLAlchemy models and DB initialization
- `services/`
  - `pdf_service.py` - PDF scanning, parsing, chunking, and ingestion
  - `embedding_service.py` - Embedding generation
  - `qdrant_service.py` - Qdrant collection and similarity search
  - `llm_service.py` - LLM streaming and provider integration
- `static/` - Frontend UI assets
- `requirements.txt` - Python dependencies
- `.env.example` - Example environment variables

## Getting Started

### Prerequisites

- Python 3.10+ (3.13 is supported)
- Docker & Docker Compose
- Local Ollama server if using `LLM_PROVIDER=ollama`

### Install dependencies

```bash
cd Vijay-ws-main
python -m pip install -r requirements.txt
```

### Configure environment

Create a `.env` file in `Vijay-ws-main` or copy from `.env.example`.

Example `.env` for Ollama:

```env
HOST=0.0.0.0
PORT=8000
DATA_DIR=./data
DATABASE_URL=mssql+pymssql://sa:SqlChatbotSecurePass!2026@localhost:1433/master
DB_NAME=pdf_chatbot
QDRANT_URL=http://localhost:6333
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=qwen2.5:7b
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
MAX_WORKERS=2
CHUNK_SIZE=600
CHUNK_OVERLAP=80
```

If using OpenAI:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4o-mini
```

### Start services

Start Docker containers for SQL Server and Qdrant if needed.

```bash
docker compose up -d
```

### Run the app

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Then open:

```text
http://127.0.0.1:8000/
```

## Usage

- Upload a PDF via the frontend or call `/api/pdf/upload`
- Wait for ingestion to complete
- Use the chat interface to ask questions about the selected PDF
- Monitor ingestion and query stats via `/api/monitoring/stats`

## API Endpoints

- `GET /` - Redirects to `/static/index.html`
- `POST /api/pdf/upload` - Upload a PDF
- `POST /api/pdf/ingest-folder` - Scan the configured data directory and ingest new PDFs
- `GET /api/pdf/files` - List ingested PDFs and status
- `POST /api/chat/ask` - Ask a question against a selected PDF
- `GET /api/monitoring/stats` - View system and application metrics

## Notes

- The `.env` file must be readable by the application and should be placed in the project root.
- The app uses a strict `pdf_name` filter when searching Qdrant so answers are drawn from the selected document only.
- Local embeddings (`EMBEDDING_PROVIDER=local`) are recommended for offline use and lower cost.


