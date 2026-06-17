import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

def count_omitted():
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    pwd = os.environ.get("NEO4J_PASSWORD", "12345678")
    
    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    
    with driver.session() as session:
        result = session.run("MATCH (e:Event) WHERE e.title CONTAINS '补充遗漏文本' RETURN count(e) AS cnt").single()
        print(f"Neo4j Event nodes with '补充遗漏文本' in title: {result['cnt']}")
        
        # Show a few examples
        examples = session.run("MATCH (e:Event) WHERE e.title CONTAINS '补充遗漏文本' RETURN e.id, e.title, e.description, e.protagonist LIMIT 5").data()
        for i, ex in enumerate(examples):
            print(f"Example {i+1}: ID={ex['e.id']}, Title={ex['e.title']}, Desc={ex['e.description'][:100]}, Protagonist={ex['e.protagonist']}")
            
    driver.close()

if __name__ == "__main__":
    count_omitted()
