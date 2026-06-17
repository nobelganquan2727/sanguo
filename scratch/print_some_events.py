import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

def print_some_events():
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    pwd = os.environ.get("NEO4J_PASSWORD", "12345678")
    
    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    
    with driver.session() as session:
        result = session.run("MATCH (e:Event) RETURN e LIMIT 3")
        for r in result:
            node = r["e"]
            print(f"ID: {node.get('id')}")
            print(f"Title: {node.get('title')}")
            print(f"Description: {node.get('description')}")
            print(f"Translation: {node.get('translation')}")
            print(f"Source: {node.get('source_text')[:100]}...")
            print("=" * 50)

if __name__ == "__main__":
    print_some_events()
