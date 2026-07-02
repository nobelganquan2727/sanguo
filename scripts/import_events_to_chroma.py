import os
import sys
import json
import requests
import chromadb
import concurrent.futures
from neo4j import GraphDatabase
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

def get_neo4j_driver():
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    pwd = os.environ.get("NEO4J_PASSWORD", "12345678")
    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    driver.verify_connectivity()
    return driver

def build_event_text(title: str, desc: str, source: str) -> str:
    title = title or ""
    desc = desc or ""
    source = source or ""
    return f"事件：{title}\n简介：{desc}\n原文：{source}"[:2000]

def embed_batch(texts: list[str]) -> list[list[float]]:
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
        "input": texts,
        "encoding_format": "float"
    }
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=20)
            res.raise_for_status()
            data = res.json()
            embeddings = [None] * len(texts)
            for item in data.get("data", []):
                idx = item.get("index")
                if idx is not None and idx < len(embeddings):
                    embeddings[idx] = item["embedding"]
            if any(e is None for e in embeddings):
                raise ValueError("Missing embedding index in API response")
            return embeddings
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            continue

def main():
    print("Connecting to Neo4j...")
    try:
        driver = get_neo4j_driver()
    except Exception as e:
        print(f"❌ Failed to connect to Neo4j: {e}")
        return

    print("Fetching all events from Neo4j...")
    cypher_fetch = """
    MATCH (e:Event)
    WHERE e.title IS NOT NULL
    RETURN e.id AS id, e.title AS title, e.description AS description, 
           e.translation AS translation, e.source_text AS source_text
    """
    try:
        with driver.session() as session:
            results = session.run(cypher_fetch)
            events = [dict(r) for r in results]
    except Exception as e:
        print(f"❌ Failed to query Neo4j: {e}")
        driver.close()
        return
    driver.close()
    
    print(f"Total events retrieved: {len(events)}")
    if not events:
        print("❌ No events found in Neo4j.")
        return

    print("Connecting to ChromaDB...")
    try:
        chroma_client = chromadb.PersistentClient(path="logs/chroma_cache")
        collection = chroma_client.get_or_create_collection(
            name="event_embeddings",
            metadata={"hnsw:space": "cosine"}
        )
    except Exception as e:
        print(f"❌ Failed to connect to ChromaDB: {e}")
        return

    # Check already imported IDs (titles) to support incremental runs
    print("Checking existing items in ChromaDB...")
    try:
        existing_ids = set(collection.get(include=[])["ids"])
        print(f"ChromaDB already has {len(existing_ids)} events.")
    except Exception as e:
        print(f"⚠️ Failed to get existing IDs from ChromaDB (starting fresh): {e}")
        existing_ids = set()

    # Filter out already embedded events
    pending_events = [e for e in events if e["id"] not in existing_ids]
    print(f"Pending events to embed: {len(pending_events)}")
    if not pending_events:
        print("🎉 All events are already embedded and stored in ChromaDB!")
        return

    # Prepare texts to embed
    texts_to_embed = []
    event_titles = []
    event_ids = []
    
    for ev in pending_events:
        title = ev["title"]
        desc = ev.get("translation") or ev.get("description") or ""
        source = ev.get("source_text") or ""
        texts_to_embed.append(build_event_text(title, desc, source))
        event_titles.append(title)
        event_ids.append(ev["id"])

    # Batch into chunks of 32
    chunk_size = 32
    chunks = [texts_to_embed[i:i + chunk_size] for i in range(0, len(texts_to_embed), chunk_size)]
    chunk_titles = [event_titles[i:i + chunk_size] for i in range(0, len(event_titles), chunk_size)]
    chunk_ids = [event_ids[i:i + chunk_size] for i in range(0, len(event_ids), chunk_size)]

    print(f"Chunked into {len(chunks)} batches. Generating embeddings using SiliconFlow (BAAI/bge-m3)...")

    # Concurrent embedding generation & import to ChromaDB
    def process_and_import(chunk_data):
        chunk, c_titles, c_ids = chunk_data
        try:
            embeddings = embed_batch(chunk)
            # Use unique Event IDs as Chroma IDs, store title in metadata
            collection.upsert(
                ids=c_ids,
                embeddings=embeddings,
                metadatas=[{"title": title} for title in c_titles]
            )
            return len(c_titles)
        except Exception as e:
            print(f"\n❌ Error processing batch: {e}")
            return 0

    import_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        tasks = [executor.submit(process_and_import, (c, t, i)) for c, t, i in zip(chunks, chunk_titles, chunk_ids)]
        for future in tqdm(concurrent.futures.as_completed(tasks), total=len(tasks), desc="Importing to ChromaDB"):
            import_count += future.result()

    print(f"\n🎉 Successfully imported {import_count} new event embeddings directly into ChromaDB!")

if __name__ == "__main__":
    main()
