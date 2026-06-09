import os
from dotenv import load_dotenv
load_dotenv()

# Force HuggingFace endpoint if defined in .env
if "HF_ENDPOINT" in os.environ:
    os.environ["HF_ENDPOINT"] = os.environ["HF_ENDPOINT"]

try:
    from sentence_transformers import SentenceTransformer
    print("Loading BAAI/bge-m3...")
    model = SentenceTransformer('BAAI/bge-m3')
    print("Model loaded successfully.")
    
    vec = model.encode("曹操在官渡之战前的部署")
    print(f"Vector length: {len(vec)}")
    print(f"Sample values: {vec[:5]}")
except Exception as e:
    print(f"Error: {e}")
