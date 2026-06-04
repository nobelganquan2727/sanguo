import os
import json
import math
import requests
from typing import Optional, Tuple

# Suppress urllib3 warnings when verify=False is used
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CACHE_FILE = "logs/semantic_cache.json"

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

def get_dashscope_embedding(text: str) -> list[float]:
    """Fetch text embedding vector from DashScope HTTP API."""
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        raise ValueError("DASHSCOPE_API_KEY not found in environment!")
        
    url = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "text-embedding-v2",
        "input": {
            "texts": [text]
        }
    }
    
    res = requests.post(url, json=payload, headers=headers, verify=False, timeout=10)
    res.raise_for_status()
    
    response = res.json()
    embeddings = response.get("output", {}).get("embeddings", [])
    if not embeddings:
        raise ValueError(f"No embeddings returned from DashScope: {response}")
    return embeddings[0]["embedding"]

def lookup_cache(question: str, threshold: float = 0.92) -> Tuple[Optional[str], float]:
    """
    Lookup a question in the local semantic cache.
    Returns (cached_answer, similarity_score) if a match above the threshold is found,
    otherwise (None, best_similarity_score).
    """
    if not os.path.exists(CACHE_FILE):
        return None, 0.0
        
    try:
        q_vector = get_dashscope_embedding(question)
    except Exception as e:
        print(f"⚠️ Failed to get embedding for cache lookup: {e}")
        return None, 0.0
        
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except Exception as e:
        print(f"⚠️ Failed to load semantic cache file: {e}")
        return None, 0.0
        
    best_sim = 0.0
    best_ans = None
    
    for entry in cache:
        cached_vec = entry.get("embedding", [])
        if not cached_vec:
            continue
            
        sim = cosine_similarity(q_vector, cached_vec)
        if sim > best_sim:
            best_sim = sim
            best_ans = entry.get("answer", "")
            
    if best_sim >= threshold:
        return best_ans, best_sim
        
    return None, best_sim

def save_cache(question: str, answer: str) -> None:
    """Save a question and its answer to the local semantic cache."""
    # Do not cache error results or standard model fallback messages
    if not answer or answer.startswith("Error") or "病体抱恙" in answer or "简牍翻阅多有不便" in answer:
        return
        
    try:
        q_vector = get_dashscope_embedding(question)
    except Exception as e:
        print(f"⚠️ Failed to get embedding for cache saving: {e}")
        return
        
    # Ensure logs folder exists
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    
    cache = []
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = []
            
    # Remove existing exact matching question to avoid duplicates
    cache = [entry for entry in cache if entry.get("question") != question]
    
    cache.append({
        "question": question,
        "answer": answer,
        "embedding": q_vector
    })
    
    # Write atomically
    try:
        tmp_file = CACHE_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, CACHE_FILE)
        print(f"💾 Saved query to semantic cache: '{question}'")
    except Exception as e:
        print(f"⚠️ Failed to write semantic cache: {e}")
