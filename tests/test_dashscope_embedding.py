import os
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings

load_dotenv()

def test_embedding():
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        print("❌ DASHSCOPE_API_KEY not found in environment!")
        return
        
    embeddings = OpenAIEmbeddings(
        model="text-embedding-v2",
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    
    try:
        vec = embeddings.embed_query("曹操是谁？")
        print(f"✅ Success! Embedding length: {len(vec)}")
        print(f"First 5 dimensions: {vec[:5]}")
    except Exception as e:
        print(f"❌ Failed to get embedding: {e}")

if __name__ == "__main__":
    test_embedding()
