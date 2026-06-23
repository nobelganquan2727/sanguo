import os
from neo4j import GraphDatabase

_driver = None

def get_driver():
    global _driver
    if _driver is None:
        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "12345678")
        _driver = GraphDatabase.driver(uri, auth=(user, password))
    return _driver

def run_query(cypher: str, params: dict = None) -> list[dict]:
    """
    Execute Cypher queries against Neo4j and return results as lists of dictionaries.
    """
    driver = get_driver()
    with driver.session() as session:
        result = session.run(cypher, params or {})
        return [dict(r) for r in result]

def close():
    global _driver
    if _driver:
        _driver.close()
        _driver = None
