import os
from config import settings

# Lazy loaded instances to avoid loading libraries unnecessarily
_fastembed_model = None

def get_fastembed_model():
    """Lazily load FastEmbed model to save startup time and memory."""
    global _fastembed_model
    if _fastembed_model is None:
        from fastembed import TextEmbedding
        print(f"Loading FastEmbed model: {settings.EMBEDDING_MODEL}...")
        _fastembed_model = TextEmbedding(model_name=settings.EMBEDDING_MODEL)
    return _fastembed_model

def get_local_embeddings(texts: list[str]) -> list[list[float]]:
    """Generate embeddings using FastEmbed locally on CPU."""
    model = get_fastembed_model()
    # embed() returns an iterable of numpy arrays
    return [list(map(float, vec)) for vec in model.embed(texts)]

def get_openai_embeddings(texts: list[str]) -> list[list[float]]:
    """Generate embeddings using OpenAI API."""
    from openai import OpenAI
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    response = client.embeddings.create(
        input=texts,
        model=settings.EMBEDDING_MODEL
    )
    return [data.embedding for data in response.data]

def get_gemini_embeddings(texts: list[str]) -> list[list[float]]:
    """Generate embeddings using Google Gemini API."""
    from google import genai
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    response = client.models.embed_content(
        model=settings.EMBEDDING_MODEL if settings.EMBEDDING_MODEL != "BAAI/bge-small-en-v1.5" else "text-embedding-004",
        contents=texts
    )
    # The embeddings can be accessed from the values list of each embedding object
    return [emb.values for emb in response.embeddings]

def get_azure_embeddings(texts: list[str]) -> list[list[float]]:
    """Generate embeddings using Azure OpenAI API."""
    from openai import AzureOpenAI
    client = AzureOpenAI(
        api_key=settings.AZURE_OPENAI_API_KEY,
        api_version=settings.AZURE_OPENAI_API_VERSION,
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT
    )
    response = client.embeddings.create(
        input=texts,
        model=settings.EMBEDDING_MODEL  # On Azure, this should map to your embedding deployment
    )
    return [data.embedding for data in response.data]

def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """
    Unified batch embedding generation interface.
    Automatically routes to the configured provider.
    """
    if not texts:
        return []
        
    provider = settings.EMBEDDING_PROVIDER.lower()
    
    if provider == "local":
        return get_local_embeddings(texts)
    elif provider == "openai":
        return get_openai_embeddings(texts)
    elif provider == "gemini":
        return get_gemini_embeddings(texts)
    elif provider == "azure":
        return get_azure_embeddings(texts)
    else:
        raise ValueError(f"Unsupported embedding provider: {provider}")

def get_embedding_dimension() -> int:
    """Return vector dimension based on the configured model and provider."""
    provider = settings.EMBEDDING_PROVIDER.lower()
    
    if provider == "local":
        model_name = settings.EMBEDDING_MODEL.lower()
        if "bge-small" in model_name:
            return 384
        elif "bge-large" in model_name:
            return 1024
        elif "bge-base" in model_name:
            return 768
        elif "minilm" in model_name:
            return 384
        return 384
    elif provider == "openai":
        model_name = settings.EMBEDDING_MODEL.lower()
        if "text-embedding-3-small" in model_name:
            return 1536
        elif "text-embedding-3-large" in model_name:
            return 3072
        elif "text-embedding-ada-002" in model_name:
            return 1536
        return 1536
    elif provider == "gemini":
        return 768
    elif provider == "azure":
        return 1536
    return 384
