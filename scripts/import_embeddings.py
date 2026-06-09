import json
import glob
import os
import re
from neo4j import GraphDatabase

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("锺", "钟")
    return re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]', '', text)

def import_embeddings():
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    pwd = os.environ.get("NEO4J_PASSWORD", "12345678")
    
    print(f"Connecting to Neo4j at {uri}...")
    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    
    try:
        driver.verify_connectivity()
    except Exception as e:
        print(f"❌ Failed to connect to Neo4j: {e}")
        return
        
    with driver.session() as session:
        # 1. Create Vector Index
        print("Creating vector index 'eventEmbeddings' if not exists...")
        create_index_query = """
        CREATE VECTOR INDEX eventEmbeddings IF NOT EXISTS
        FOR (e:Event) ON (e.embedding)
        OPTIONS {
          indexConfig: {
            `vector.dimensions`: 1024,
            `vector.similarity_function`: 'cosine'
          }
        }
        """
        session.run(create_index_query)
        
        # 2. Retrieve all events in the database to map descriptions
        print("Fetching events from Neo4j for mapping...")
        results = session.run("MATCH (e:Event) RETURN e.id AS id, e.description AS description")
        neo4j_events = [dict(r) for r in results]
        
        normalized_raw_map = {}
        for ev in neo4j_events:
            desc = ev["description"]
            if desc:
                normalized_raw_map[normalize_text(desc)] = ev["id"]
                
        print(f"Mapped {len(normalized_raw_map)} events from Neo4j.")
        
        # 3. Read vector JSON files and prepare updates
        vector_files = glob.glob("data/vectors_bgem3/*_events.json")
        batch = []
        matched_count = 0
        total_count = 0
        
        for v_file in vector_files:
            with open(v_file, 'r', encoding='utf-8') as f:
                events = json.load(f)
            for e in events:
                total_count += 1
                doc = e.get("document", "")
                embedding = e.get("embedding")
                
                if not embedding:
                    continue
                    
                match = re.search(r'简介：(.*?)\n原文：', doc, re.DOTALL)
                if match:
                    brief = match.group(1).strip()
                    norm_brief = normalize_text(brief)
                    
                    if norm_brief in normalized_raw_map:
                        event_id = normalized_raw_map[norm_brief]
                        batch.append({"id": event_id, "embedding": embedding})
                        matched_count += 1
                        
            # Execute batch updates
            if len(batch) >= 500:
                print(f"Updating batch of {len(batch)} event embeddings in Neo4j...")
                update_query = """
                UNWIND $batch AS row
                MATCH (e:Event {id: row.id})
                SET e.embedding = row.embedding
                """
                session.run(update_query, {"batch": batch})
                batch = []
                
        # Update any remaining in the batch
        if batch:
            print(f"Updating final batch of {len(batch)} event embeddings in Neo4j...")
            update_query = """
            UNWIND $batch AS row
            MATCH (e:Event {id: row.id})
            SET e.embedding = row.embedding
            """
            session.run(update_query, {"batch": batch})
            
        print(f"🎉 Successfully imported {matched_count} / {total_count} embeddings!")
        
    driver.close()

if __name__ == "__main__":
    import_embeddings()
