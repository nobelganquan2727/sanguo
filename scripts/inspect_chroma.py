import os
import sys
import argparse
import chromadb
from dotenv import load_dotenv

# Add project root to path to import agent modules if needed
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.cache import get_bge_m3_embedding

def main():
    load_dotenv()
    
    parser = argparse.ArgumentParser(description="🔍 ChromaDB Semantic Cache Inspect Tool")
    parser.add_argument("--limit", type=int, default=10, help="Limit the number of printed results (default: 10)")
    parser.add_argument("--query", type=str, help="Search semantic cache with a question (returns top matches)")
    parser.add_argument("--all", action="store_true", help="List all entries in the cache")
    parser.add_argument("--delete", type=str, help="Delete a specific question from the cache by ID/Question")
    parser.add_argument("--clear", action="store_true", help="Clear the entire semantic cache")
    
    args = parser.parse_args()
    
    db_path = "logs/chroma_cache"
    if not os.path.exists(db_path):
        print(f"❌ ChromaDB path '{db_path}' does not exist yet. Run some queries first.")
        return
        
    client = chromadb.PersistentClient(path=db_path)
    collection = client.get_or_create_collection(
        name="semantic_cache",
        metadata={"hnsw:space": "cosine"}
    )
    
    total = collection.count()
    print(f"📊 Total Cache Entries: {total}")
    print("=" * 60)
    
    if args.clear:
        confirm = input("⚠️ Are you sure you want to clear the ENTIRE cache? (y/n): ")
        if confirm.lower() == 'y':
            client.delete_collection("semantic_cache")
            print("扫 Cache cleared successfully.")
        return
        
    if args.delete:
        collection.delete(ids=[args.delete])
        print(f"🗑️ Deleted entry: '{args.delete}'")
        return
        
    if args.query:
        print(f"🧠 Querying semantic cache for: '{args.query}'")
        try:
            q_vector = get_bge_m3_embedding(args.query)
            results = collection.query(
                query_embeddings=[q_vector],
                n_results=3
            )
            if not results or not results.get("ids") or len(results["ids"][0]) == 0:
                print("📭 No matches found.")
                return
                
            for idx in range(len(results["ids"][0])):
                question = results["ids"][0][idx]
                distance = results["distances"][0][idx]
                similarity = 1.0 - distance
                answer = results["metadatas"][0][idx].get("answer", "")
                
                print(f"\nMatch #{idx+1} (Similarity: {similarity:.4f})")
                print(f"Q: {question}")
                print(f"A: {answer}")
                print("-" * 40)
        except Exception as e:
            print(f"❌ Failed to query: {e}. Make sure SILICONFLOW_API_KEY is configured in your environment.")
        return
        
    # Default behavior or --all
    limit = total if args.all else args.limit
    if total == 0:
        print("📭 Cache is currently empty.")
        return
        
    print(f"Listing top {limit} entries:")
    data = collection.get(limit=limit, include=["metadatas"])
    for i in range(len(data["ids"])):
        question = data["ids"][i]
        answer = data["metadatas"][i].get("answer", "")
        # Truncate answer for display
        truncated_ans = answer.replace("\n", " ")
        if len(truncated_ans) > 80:
            truncated_ans = truncated_ans[:80] + "..."
            
        print(f"\n[{i+1}] Q: {question}")
        print(f"    A: {truncated_ans}")

if __name__ == "__main__":
    main()
