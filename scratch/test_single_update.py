import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

def test_update():
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    pwd = os.environ.get("NEO4J_PASSWORD", "12345678")
    
    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    
    mock_vector = [0.1] * 1024
    
    with driver.session() as session:
        # Get one node ID
        result = session.run("MATCH (e:Event) RETURN e.id AS id LIMIT 1").single()
        if not result:
            print("No node found")
            return
        node_id = result["id"]
        print(f"Targeting Node ID: {node_id}")
        
        # Update
        update_res = session.run(
            "MATCH (e:Event {id: $id}) SET e.embedding = $embedding RETURN e.id, e.embedding",
            {"id": node_id, "embedding": mock_vector}
        ).single()
        
        if update_res:
            print("Successfully updated return values:")
            print("ID:", update_res["e.id"])
            print("Embedding length:", len(update_res["e.embedding"]) if update_res["e.embedding"] else "None")
        else:
            print("Update returned nothing!")
            
        # Re-fetch to check if it persisted
        check_res = session.run("MATCH (e:Event {id: $id}) RETURN e.embedding", {"id": node_id}).single()
        print("Re-fetched embedding length:", len(check_res["e.embedding"]) if check_res["e.embedding"] else "None")

if __name__ == "__main__":
    test_update()
