import asyncio
import sys
import os
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.tools import run_query_async

async def main():
    cypher1 = """
    MATCH (p:Person {name: '张郃'})-[r:PARTICIPATED_IN]->(e:Event)
    RETURN e.title AS title, e.std_start_year AS year
    """
    
    cypher2 = """
    MATCH (p:Person {name: '诸葛亮'})-[r:PARTICIPATED_IN]->(e:Event)
    RETURN e.title AS title, e.std_start_year AS year
    """
    
    cypher3 = """
    MATCH (e:Event)
    WHERE e.title CONTAINS '张郃' OR e.title CONTAINS '街亭'
    RETURN e.title AS title, e.std_start_year AS year
    """
    
    print("--- 1. Zhang He Timeline Events in Neo4j ---")
    results1 = await run_query_async(cypher1)
    for r in results1:
        print(f"  - {r['title']} ({r['year']})")
        
    print("\n--- 2. Zhuge Liang Timeline Events in Neo4j ---")
    results2 = await run_query_async(cypher2)
    for r in results2:
        print(f"  - {r['title']} ({r['year']})")

    print("\n--- 3. Events containing '张郃' or '街亭' in title ---")
    results3 = await run_query_async(cypher3)
    for r in results3:
        print(f"  - {r['title']} ({r['year']})")

if __name__ == "__main__":
    asyncio.run(main())
