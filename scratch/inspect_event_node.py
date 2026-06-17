import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

def inspect_node():
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    pwd = os.environ.get("NEO4J_PASSWORD", "12345678")
    
    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    
    with driver.session() as session:
        # Get one event and all its keys
        result = session.run("MATCH (e:Event) RETURN e LIMIT 1").single()
        if result:
            node = result["e"]
            print("Keys:", list(node.keys()))
            print("ID:", node.get("id"))
            print("Embedding value preview:", str(node.get("embedding"))[:200])
        else:
            print("No event node found")

if __name__ == "__main__":
    inspect_node()
