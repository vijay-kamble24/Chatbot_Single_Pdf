from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from config import settings
from services.embedding_service import get_embedding_dimension

# Lazy-loaded Qdrant client
_client = None
COLLECTION_NAME = "pdf_chunks"

def get_qdrant_client() -> QdrantClient:
    """Lazily initialize the Qdrant client."""
    global _client
    if _client is None:
        _client = QdrantClient(url=settings.QDRANT_URL)
    return _client

def ensure_collection():
    """Ensure the target collection exists in Qdrant with correct settings."""
    client = get_qdrant_client()
    
    try:
        # Check if collection exists
        collections = client.get_collections().collections
        exists = any(c.name == COLLECTION_NAME for c in collections)
        
        if not exists:
            dim = get_embedding_dimension()
            print(f"Creating Qdrant collection '{COLLECTION_NAME}' with dimension {dim}...")
            client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=qmodels.VectorParams(
                    size=dim,
                    distance=qmodels.Distance.COSINE
                )
            )
            # Create payload index on pdf_name for fast O(1) filtering
            client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name="pdf_name",
                field_schema=qmodels.PayloadSchemaType.KEYWORD
            )
            print(f"Collection '{COLLECTION_NAME}' created and indexed successfully.")
    except Exception as e:
        print(f"Error ensuring Qdrant collection: {e}")
        # Re-raise to let caller handle it
        raise e

def store_vectors(ids: list[str], embeddings: list[list[float]], payloads: list[dict]):
    """Upsert vectors and payloads into Qdrant."""
    client = get_qdrant_client()
    ensure_collection()
    
    points = [
        qmodels.PointStruct(
            id=pt_id,
            vector=emb,
            payload=pay
        )
        for pt_id, emb, pay in zip(ids, embeddings, payloads)
    ]
    
    # Batch upsert points
    client.upsert(
        collection_name=COLLECTION_NAME,
        points=points
    )
    print(f"Successfully upserted {len(points)} vectors to Qdrant.")

def delete_vectors_by_pdf_name(pdf_name: str):
    """Delete all vectors matching a specific PDF document name."""
    client = get_qdrant_client()
    ensure_collection()
    
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=qmodels.FilterSelector(
            filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="pdf_name",
                        match=qmodels.MatchValue(value=pdf_name)
                    )
                ]
            )
        )
    )
    print(f"Deleted vectors in Qdrant for PDF name: {pdf_name}")

def similarity_search(pdf_name: str, query_vector: list[float], limit: int = 5) -> list[dict]:
    """
    Perform a similarity search in Qdrant, STRICTLY filtered by the selected PDF name.
    Guarantees no cross-contamination between documents.
    """
    client = get_qdrant_client()
    ensure_collection()
    
    response = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        query_filter=qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="pdf_name",
                    match=qmodels.MatchValue(value=pdf_name)
                )
            ]
        ),
        limit=limit
    )
    
    # Extract payload from each hit
    return [hit.payload for hit in response.points]
