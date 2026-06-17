import os
import sys
import json
import requests
import concurrent.futures
from neo4j import GraphDatabase
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

def get_driver():
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
    
    # Retry on transient failures
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
        driver = get_driver()
    except Exception as e:
        print(f"❌ Failed to connect to Neo4j: {e}")
        return

    print("Fetching events from Neo4j that do not have embeddings yet...")
    cypher_fetch = """
    MATCH (e:Event)
    WHERE e.embedding IS NULL
    RETURN e.id AS id, e.title AS title, e.description AS description, 
           e.translation AS translation, e.source_text AS source_text
    """
    with driver.session() as session:
        results = session.run(cypher_fetch)
        events = [dict(r) for r in results]
    driver.close()
    
    print(f"Total events retrieved: {len(events)}")
    if not events:
        print("❌ No events found in database.")
        return

    # Prepare texts to embed
    texts_to_embed = []
    event_ids = []
    for ev in events:
        title = ev.get("title") or ""
        desc = ev.get("translation") or ev.get("description") or ""
        source = ev.get("source_text") or ""
        texts_to_embed.append(build_event_text(title, desc, source))
        event_ids.append(ev["id"])

    # Batch into chunks of 32
    chunk_size = 32
    chunks = [texts_to_embed[i:i + chunk_size] for i in range(0, len(texts_to_embed), chunk_size)]
    chunk_ids = [event_ids[i:i + chunk_size] for i in range(0, len(event_ids), chunk_size)]

    print(f"Chunked into {len(chunks)} batches. Generating embeddings using SiliconFlow (BAAI/bge-m3)...")

    results_to_import = []
    
    # Concurrent embedding generation
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(embed_batch, chunk): (chunk, c_ids) for chunk, c_ids in zip(chunks, chunk_ids)}
        
        for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc="Generating Embeddings"):
            chunk, c_ids = futures[future]
            try:
                embeddings = future.result()
                for eid, emb in zip(c_ids, embeddings):
                    if emb:
                        results_to_import.append({"id": eid, "embedding": emb})
            except Exception as e:
                print(f"\n❌ Error generating embedding for batch: {e}")

    print(f"\nGenerated {len(results_to_import)} event embeddings.")

    # Write embeddings to Neo4j in batches
    batch_write_size = 500
    write_batches = [results_to_import[i:i + batch_write_size] for i in range(0, len(results_to_import), batch_write_size)]
    
    print("Re-connecting to Neo4j for writing...")
    try:
        driver = get_driver()
    except Exception as e:
        print(f"❌ Failed to reconnect to Neo4j: {e}")
        return

    print(f"Updating Neo4j in {len(write_batches)} batches...")
    
    cypher_update = """
    UNWIND $batch AS row
    MATCH (e:Event {id: row.id})
    SET e.embedding = row.embedding
    """
    
    with driver.session() as session:
        for idx, batch in enumerate(write_batches):
            try:
                session.run(cypher_update, {"batch": batch})
                print(f"  🚀 Batch {idx+1}/{len(write_batches)} written ({len(batch)} nodes)")
            except Exception as e:
                print(f"  ❌ Batch {idx+1} write failed: {e}")

    # Ensure index exists
    print("Ensuring eventEmbeddings vector index exists...")
    create_index = """
    CREATE VECTOR INDEX eventEmbeddings IF NOT EXISTS
    FOR (e:Event) ON (e.embedding)
    OPTIONS {
      indexConfig: {
        `vector.dimensions`: 1024,
        `vector.similarity_function`: 'cosine'
      }
    }
    """
    with driver.session() as session:
        session.run(create_index)
        print("🎉 Successfully completed embedding generation and import!")

    driver.close()

if __name__ == "__main__":
    main()
