import os
import json
import requests
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

def get_bge_embedding(text: str) -> list[float]:
    api_key = os.environ.get("SILICONFLOW_API_KEY")
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
    return res.json()["data"][0]["embedding"]

def search_vector(query_text: str, k: int = 5):
    embedding = get_bge_embedding(query_text)
    
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    pwd = os.environ.get("NEO4J_PASSWORD", "12345678")
    
    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    
    cypher = """
    CALL db.index.vector.queryNodes('eventEmbeddings', $k, $embedding)
    YIELD node, score
    MATCH (node:Event)
    OPTIONAL MATCH (node)-[:HAPPENED_AT]->(l:Location)
    OPTIONAL MATCH (node)-[:BELONGS_TO_MAJOR]->(me:MajorEvent)
    RETURN node.id AS id, node.title AS title, node.description AS description, 
           node.translation AS translation, node.time_text AS time, node.std_start_year AS year, 
           node.source_text AS source, collect(DISTINCT l.name) AS locations, 
           me.title AS major_event, score
    ORDER BY score DESC
    """
    
    with driver.session() as session:
        results = session.run(cypher, {"k": k, "embedding": embedding})
        return [dict(r) for r in results]

if __name__ == "__main__":
    query = "荀彧的四胜论"
    print(f"Searching for: {query}")
    try:
        results = search_vector(query)
        for r in results:
            print(f"Score: {r['score']:.4f} | Title: {r['title']} | Year: {r['year']}")
            print(f"Desc: {r['description'][:100]}...")
            print("-" * 50)
    except Exception as e:
        print(f"❌ Error: {e}")
