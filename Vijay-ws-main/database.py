import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, UnicodeText, text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from config import settings

# Base class for declarative models
Base = declarative_base()

class PDFDocument(Base):
    __tablename__ = "pdfs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    folder_name = Column(String(255), nullable=False)
    file_path = Column(String(1000), nullable=False)
    checksum = Column(String(64), nullable=False, unique=True)
    status = Column(String(50), nullable=False, default="PENDING")  # PENDING, PROCESSING, COMPLETED, FAILED
    total_chunks = Column(Integer, default=0)
    error_message = Column(String(2000), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    chunks = relationship("PDFChunk", back_populates="pdf", cascade="all, delete-orphan")

class PDFChunk(Base):
    __tablename__ = "pdf_chunks"

    id = Column(String(100), primary_key=True)  # unique string id e.g. "pdf_id_chunk_index"
    pdf_id = Column(Integer, ForeignKey("pdfs.id", ondelete="CASCADE"), nullable=False)
    pdf_name = Column(String(255), nullable=False)
    folder_name = Column(String(255), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    page_number = Column(Integer, nullable=False)
    chunk_text = Column(UnicodeText, nullable=False)  # NVARCHAR(MAX) in SQL Server
    embedding_status = Column(String(50), nullable=False, default="PENDING")  # PENDING, COMPLETED, FAILED
    checksum = Column(String(64), nullable=False)  # hash of chunk contents
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    pdf = relationship("PDFDocument", back_populates="chunks")

# Database setup engine placeholders
_engine = None
_SessionLocal = None

def get_db_url_for_app_db():
    """Generates URL pointing to the actual application database instead of master."""
    url = settings.DATABASE_URL
    if "/" in url:
        base_url, db_part = url.rsplit("/", 1)
        # Handle connection params if present (e.g. ?charset=utf8)
        if "?" in db_part:
            db_name_part, query_params = db_part.split("?", 1)
            return f"{base_url}/{settings.DB_NAME}?{query_params}"
        else:
            return f"{base_url}/{settings.DB_NAME}"
    return url

def init_db():
    """Initializes the database. Checks if it exists, creates if not, and creates all tables."""
    global _engine, _SessionLocal
    
    # 1. Connect to master to check/create the target database
    master_url = settings.DATABASE_URL
    print(f"Connecting to SQL Server master database at {master_url} to ensure DB exists...")
    
    # pymssql requires autocommit to be True to run CREATE DATABASE (cannot run in transaction)
    master_engine = create_engine(master_url, connect_args={"autocommit": True})
    
    with master_engine.connect() as conn:
        # Query sys.databases
        result = conn.execute(text(f"SELECT database_id FROM sys.databases WHERE name = '{settings.DB_NAME}'"))
        db_exists = result.scalar() is not None
        if not db_exists:
            print(f"Database '{settings.DB_NAME}' does not exist. Creating...")
            conn.execute(text(f"CREATE DATABASE {settings.DB_NAME}"))
            print(f"Database '{settings.DB_NAME}' created successfully.")
        else:
            print(f"Database '{settings.DB_NAME}' already exists.")
            
    master_engine.dispose()
    
    # 2. Setup the engine for our application database
    db_url = get_db_url_for_app_db()
    print(f"Connecting to SQL Server application database at {db_url}...")
    _engine = create_engine(
        db_url, 
        pool_pre_ping=True, 
        pool_size=10, 
        max_overflow=20
    )
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    
    # 3. Create all tables
    Base.metadata.create_all(bind=_engine)
    print("Database tables initialized successfully.")

def get_db():
    """Dependency to retrieve a database session."""
    global _SessionLocal
    if _SessionLocal is None:
        init_db()
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
