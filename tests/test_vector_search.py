import os
import re
from dotenv import load_dotenv
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer

load_dotenv()

# Force HF mirror
if "HF_ENDPOINT" in os.environ:
    os.environ["HF_ENDPOINT"] = os.environ["HF_ENDPOINT"]

# Load BGE-M3
model = SentenceTransformer('BAAI/bge-m3')

# Connect to Neo4j
uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
user = os.environ.get("NEO4J_USER", "neo4j")
pwd = os.environ.get("NEO4J_PASSWORD", "12345678")

driver = GraphDatabase.driver(uri, auth=(user, pwd))

query_text = "曹操在官渡之战前的部署"
query_vector = list(map(float, model.encode(query_text)))

cypher = """
CALL db.index.vector.queryNodes('eventEmbeddings', 3, $query_vector)
YIELD node, score
OPTIONAL MATCH (node)-[:HAPPENED_AT]->(l:Location)
OPTIONAL MATCH (p:Person)-[:PARTICIPATED_IN]->(node)
RETURN node.title AS title, node.description AS description, 
       collect(DISTINCT l.name) AS locations, 
       collect(DISTINCT p.name) AS participants, score
"""

with driver.session() as session:
    results = session.run(cypher, {"query_vector": query_vector})
    for r in results:
        print("=" * 60)
        print(f"Title: {r['title']} (Score: {r['score']:.4f})")
        print(f"Description: {r['description']}")
        print(f"Locations: {r['locations']}")
        print(f"Participants: {r['participants']}")

driver.close()
