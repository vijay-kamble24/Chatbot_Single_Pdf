import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

# Determine .env location relative to this config file.
BASE_DIR = os.path.dirname(__file__)
ENV_PATH = os.path.join(BASE_DIR, ".env")
if not os.path.exists(ENV_PATH):
    ENV_PATH = os.path.join(os.path.dirname(BASE_DIR), ".env")

# Load .env explicitly so pydantic has environment values available.
if os.path.exists(ENV_PATH):
    load_dotenv(ENV_PATH, override=True)

class Settings(BaseSettings):
    # Server configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DATA_DIR: str = "./data"

    # SQL Server Database Configuration
    DATABASE_URL: str = Field(default="mssql+pymssql://sa:SqlChatbotSecurePass!2026@localhost:1433/master")
    DB_NAME: str = Field(default="pdf_chatbot")

    # Vector DB configuration
    QDRANT_URL: str = Field(default="http://localhost:6333")

    # LLM configuration (openai, gemini, azure, ollama)
    LLM_PROVIDER: str = Field(default="openai")
    OPENAI_API_KEY: str = Field(default="")
    OPENAI_MODEL: str = Field(default="gpt-4o-mini")

    # Ollama local LLM configuration
    OLLAMA_BASE_URL: str = Field(default="http://localhost:11434/v1")
    OLLAMA_MODEL: str = Field(default="qwen2.5:7b")
    
    GEMINI_API_KEY: str = Field(default="")
    GEMINI_MODEL: str = Field(default="gemini-2.5-flash")

    # Azure OpenAI Configuration
    AZURE_OPENAI_API_KEY: str = Field(default="")
    AZURE_OPENAI_ENDPOINT: str = Field(default="")
    AZURE_OPENAI_DEPLOYMENT: str = Field(default="")
    AZURE_OPENAI_API_VERSION: str = Field(default="2024-02-15-preview")

    # Embedding configuration (local, openai, gemini, azure)
    EMBEDDING_PROVIDER: str = Field(default="local")
    EMBEDDING_MODEL: str = Field(default="BAAI/bge-small-en-v1.5")

    # Tuning parameters
    MAX_WORKERS: int = Field(default=2)
    CHUNK_SIZE: int = Field(default=600)
    CHUNK_OVERLAP: int = Field(default=80)

    model_config = SettingsConfigDict(
        env_file=ENV_PATH if os.path.exists(ENV_PATH) else ".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

# Instantiate settings
settings = Settings()
