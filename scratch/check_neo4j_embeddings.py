import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

def check_embeddings():
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    pwd = os.environ.get("NEO4J_PASSWORD", "12345678")
    
    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    
    with driver.session() as session:
        # Count all events
        r1 = session.run("MATCH (e:Event) RETURN count(e) AS cnt").single()
        # Count events with embedding
        r2 = session.run("MATCH (e:Event) WHERE e.embedding IS NOT NULL RETURN count(e) AS cnt").single()
        # Check index
        r3 = session.run("SHOW VECTOR INDEXES").data()
        
        print(f"Total events: {r1['cnt']}")
        print(f"Events with embedding: {r2['cnt']}")
        print("Vector Indexes:")
        for idx in r3:
            print(f" - Name: {idx['name']}, State: {idx['state']}, PopulationPercent: {idx.get('populationPercent', 'N/A')}")

if __name__ == "__main__":
    check_embeddings()
