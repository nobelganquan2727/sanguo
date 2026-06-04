import json
from neo4j import GraphDatabase

def get_local_locations():
    uri = "bolt://localhost:7687"
    user = "neo4j"
    pwd = "12345678"
    
    try:
        driver = GraphDatabase.driver(uri, auth=(user, pwd))
        driver.verify_connectivity()
        
        with driver.session() as session:
            result = session.run("MATCH (l:Location) RETURN l.name AS name, l.region AS region, l.lat AS lat, l.lng AS lng ORDER BY l.name")
            locations = []
            for record in result:
                locations.append({
                    "name": record["name"],
                    "region": record["region"],
                    "lat": record["lat"],
                    "lng": record["lng"]
                })
        
        driver.close()
        print(json.dumps(locations, ensure_ascii=False, indent=2))
        print(f"\n总计: {len(locations)} 个地点")
        
    except Exception as e:
        print(f"Error connecting to local Neo4j: {e}")

if __name__ == "__main__":
    get_local_locations()
