import os
import requests
from dotenv import load_dotenv

load_dotenv()

def test_siliconflow_embedding(text: str) -> list[float]:
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
    
    res = requests.post(url, json=payload, headers=headers, timeout=10)
    res.raise_for_status()
    
    response = res.json()
    embedding = response.get("data", [{}])[0].get("embedding", [])
    return embedding

if __name__ == "__main__":
    try:
        vec = test_siliconflow_embedding("曹操")
        print(f"✅ SiliconFlow Success! Length: {len(vec)}")
        print(f"First 5 dimensions: {vec[:5]}")
    except Exception as e:
        print(f"❌ SiliconFlow Failed: {e}")
