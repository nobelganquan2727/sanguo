import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

def test_unwind():
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    pwd = os.environ.get("NEO4J_PASSWORD", "12345678")
    
    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    
    batch = [
        {"id": "evt_552d3e43", "embedding": [0.2] * 1024}
    ]
    
    with driver.session() as session:
        # Reset first
        session.run("MATCH (e:Event {id: 'evt_552d3e43'}) SET e.embedding = null")
        
        # Unwind update
        cypher_update = """
        UNWIND $batch AS row
        MATCH (e:Event {id: row.id})
        SET e.embedding = row.embedding
        RETURN e.id AS id, e.embedding AS embedding
        """
        result = session.run(cypher_update, {"batch": batch}).data()
        print("Result:", result)
        if result:
            print("Embedding len:", len(result[0]["embedding"]))
        else:
            print("No match found in UNWIND!")

if __name__ == "__main__":
    test_unwind()
