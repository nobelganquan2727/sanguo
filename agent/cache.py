import os
import sys
import json
import math
import requests
import chromadb
from typing import Optional, Tuple

# Suppress urllib3 warnings when verify=False is used
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_FILE = os.path.join(PROJECT_ROOT, "logs", "semantic_cache.json")

# Detect if running under a testing framework
IS_TESTING = "unittest" in sys.modules or "pytest" in sys.modules

if IS_TESTING:
    # Use EphemeralClient for testing to isolate test cases and allow 3D mock embeddings
    client = chromadb.EphemeralClient()
else:
    # Use PersistentClient for production caching
    client = chromadb.PersistentClient(path=os.path.join(PROJECT_ROOT, "logs", "chroma_cache"))

def _get_collection():
    return client.get_or_create_collection(
        name="semantic_cache",
        metadata={"hnsw:space": "cosine"}
    )

def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Calculate the cosine similarity between two vectors."""
    if len(v1) != len(v2) or not v1 or not v2:
        return 0.0
    dot_prod = sum(a * b for a, b in zip(v1, v2))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot_prod / (norm_a * norm_b)

def get_bge_m3_embedding(text: str) -> list[float]:
    """Fetch BGE-M3 embedding from SiliconFlow API synchronously."""
    api_key = os.environ.get("SILICONFLOW_API_KEY")
    if not api_key:
        raise ValueError("SILICONFLOW_API_KEY not found in environment!")
        
    url = "https://api.siliconflow.cn/v1/embeddings"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "BAAI/bge-m3",
        "input": text,
        "encoding_format": "float"
    }
    
    res = requests.post(url, json=payload, headers=headers, verify=False, timeout=10)
    res.raise_for_status()
    
    response = res.json()
    embeddings = response.get("data", [{}])[0].get("embedding", [])
    if not embeddings:
        raise ValueError(f"No embeddings returned from SiliconFlow: {response}")
    return embeddings

def lookup_cache(question: str, threshold: float = 0.92) -> Tuple[Optional[str], Optional[list], float]:
    """
    Lookup a question in the local semantic cache.
    Returns (cached_answer, map_events, similarity_score) if a match above the threshold is found,
    otherwise (None, None, best_similarity_score).
    """
    if not os.path.exists(CACHE_FILE):
        try:
            client.delete_collection("semantic_cache")
        except Exception:
            pass
        return None, None, 0.0
        
    try:
        q_vector = get_bge_m3_embedding(question)
    except Exception as e:
        print(f"⚠️ Failed to get embedding for cache lookup: {e}")
        return None, None, 0.0
        
    try:
        collection = _get_collection()
        results = collection.query(
            query_embeddings=[q_vector],
            n_results=1
        )
    except Exception as e:
        print(f"⚠️ Failed to query ChromaDB collection: {e}")
        return None, None, 0.0
        
    if not results or not results.get("ids") or len(results["ids"][0]) == 0:
        return None, None, 0.0
        
    distance = results["distances"][0][0]
    similarity = 1.0 - distance
    if similarity >= 0.99999:
        similarity = 1.0
        
    metadata = results["metadatas"][0][0]
    answer = metadata.get("answer", "")
    map_events_str = metadata.get("map_events")
    map_events = None
    if map_events_str:
        try:
            map_events = json.loads(map_events_str)
        except Exception:
            pass
     
    if similarity >= threshold:
        return answer, map_events, similarity
        
    return None, None, similarity


def save_cache(question: str, answer: str, map_events: Optional[list] = None) -> None:
    """Save a question, its answer, and associated map events to the local semantic cache."""
    # Do not cache error results or standard model fallback messages
    if not answer or answer.startswith("Error") or "病体抱恙" in answer or "简牍翻阅多有不便" in answer:
        return
        
    try:
        q_vector = get_bge_m3_embedding(question)
    except Exception as e:
        print(f"⚠️ Failed to get embedding for cache saving: {e}")
        return
        
    # Ensure logs folder exists
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    try:
        if not os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                f.write("{}")
    except Exception as e:
        print(f"⚠️ Failed to write CACHE_FILE placeholder: {e}")
        
    try:
        collection = _get_collection()
        metadata = {"answer": answer}
        if map_events:
            metadata["map_events"] = json.dumps(map_events, ensure_ascii=False)
            
        collection.upsert(
            ids=[question],
            embeddings=[q_vector],
            metadatas=[metadata]
        )
        print(f"💾 Saved query to semantic cache: '{question}'")
    except Exception as e:
        print(f"⚠️ Failed to write to ChromaDB: {e}")

def get_event_embeddings_collection():
    """Retrieve or create the event embeddings collection in ChromaDB."""
    return client.get_or_create_collection(
        name="event_embeddings",
        metadata={"hnsw:space": "cosine"}
    )

