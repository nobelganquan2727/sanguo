"""
Neo4j 连接客户端
封装数据库连接、查询执行和自动重试逻辑
"""
import os
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

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
    执行 Cypher 查询，返回结果列表。
    如果执行失败抛出异常，交由上层处理。
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
