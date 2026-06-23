"""
Neo4j 连接客户端
封装数据库连接、查询执行和自动重试逻辑
"""
try:
    from backend.db.neo4j import run_query, get_driver, close
except ImportError:
    import sys
    import os
    _base_dir = os.path.dirname(os.path.abspath(__file__))
    _root_dir = os.path.dirname(_base_dir)
    _backend_dir = os.path.join(_root_dir, "backend")
    if _backend_dir not in sys.path:
        sys.path.append(_backend_dir)
    
    # Use dynamic import to prevent static analysis linter warnings
    db_neo4j = __import__('db.neo4j', fromlist=['run_query', 'get_driver', 'close'])
    run_query = db_neo4j.run_query
    get_driver = db_neo4j.get_driver
    close = db_neo4j.close
