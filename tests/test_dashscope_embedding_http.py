import os
import requests
from dotenv import load_dotenv

# Suppress urllib3 warnings when verify=False is used
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

def get_dashscope_embedding(text: str) -> list[float]:
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
    
    res = requests.post(url, json=payload, headers=headers, verify=False)
    res.raise_for_status()
    
    response = res.json()
    embeddings = response.get("output", {}).get("embeddings", [])
    if not embeddings:
        raise ValueError(f"No embeddings returned: {response}")
    return embeddings[0]["embedding"]

def test():
    try:
        vec = get_dashscope_embedding("曹操是谁？")
        print(f"✅ Success! Embedding length: {len(vec)}")
        print(f"First 5 dimensions: {vec[:5]}")
    except Exception as e:
        print(f"❌ Failed: {e}")

if __name__ == "__main__":
    test()
