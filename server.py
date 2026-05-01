import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from agent.qa_agent import ask_question
from agent.graph_client import run_query

app = FastAPI(title="Sanguozhi Map API")

# Add CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AskRequest(BaseModel):
    question: str

class FeedbackRequest(BaseModel):
    event_id: str
    event_title: str
    field_name: str
    proposed_value: str

import pymysql
import os

def get_db_connection():
    return pymysql.connect(
        host=os.getenv('MYSQL_HOST', 'localhost'),
        user=os.getenv('MYSQL_USER', 'root'),
        password=os.getenv('MYSQL_PASSWORD', '123456'),
        database=os.getenv('MYSQL_DB', 'sanguo'),
        cursorclass=pymysql.cursors.DictCursor
    )

@app.post("/api/feedback")
async def api_feedback(req: FeedbackRequest):
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "INSERT INTO feedback (event_id, event_title, field_name, proposed_value) VALUES (%s, %s, %s, %s)"
            cursor.execute(sql, (req.event_id, req.event_title, req.field_name, req.proposed_value))
        conn.commit()
        conn.close()
        return {"success": True, "message": "Feedback submitted successfully."}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/api/ask")
async def api_ask(req: AskRequest):
    # 调用大模型与图数据库交互
    answer = ask_question(req.question)
    return {"answer": answer}

@app.get("/api/events")
async def api_events(
    start: int, end: int,
    person_include: str = "",
    person_or: str = "",
    person_exclude: str = "",
    location: str = "",
    event_type: str = ""
):
    where_clauses = [
        # 有年份的事件才做时间范围过滤；没有年份的事件(std_start_year IS NULL)也包含进来
        f"(e.std_start_year IS NULL OR (e.std_start_year >= {start} AND e.std_start_year <= {end}))",
    ]

    # 包含人物（AND 逻辑）：每个名字都必须有参与记录
    if person_include:
        names = [n.strip() for n in person_include.split(',') if n.strip()]
        for n in names:
            where_clauses.append(f"EXISTS {{ MATCH (per:Person)-[:PARTICIPATED_IN]->(e) WHERE per.name CONTAINS '{n}' }}")

    # 包含人物（OR 逻辑）：至少有一个名字有参与记录
    if person_or:
        names = [n.strip() for n in person_or.split(',') if n.strip()]
        if names:
            cond = ' OR '.join([f"per.name CONTAINS '{n}'" for n in names])
            where_clauses.append(f"EXISTS {{ MATCH (per:Person)-[:PARTICIPATED_IN]->(e) WHERE {cond} }}")

    # 排除人物：逗号分隔，所有均不得匹配
    if person_exclude:
        names = [n.strip() for n in person_exclude.split(',') if n.strip()]
        if names:
            cond = ' OR '.join([f"per.name CONTAINS '{n}'" for n in names])
            where_clauses.append(f"NOT EXISTS {{ MATCH (per:Person)-[:PARTICIPATED_IN]->(e) WHERE {cond} }}")

    # 事件类型
    if event_type:
        where_clauses.append(f"e.type = '{event_type}'")

    loc_filter = f"WHERE '{location}' IN locations" if location else ""

    cypher = f"""
    MATCH (e:Event)
    WHERE {' AND '.join(where_clauses)}
    OPTIONAL MATCH (e)-[:HAPPENED_AT]->(l:Location)
    WITH e, collect(DISTINCT l.name) AS locations
    {loc_filter}
    RETURN e.id AS id, e.title AS title, e.std_start_year AS year,
           e.description AS desc, e.source_text AS source_text, e.type AS type, locations
    ORDER BY e.std_start_year ASC
    LIMIT 500
    """
    print(f"\n{'='*60}")
    print(f"[/api/events] AND={person_include!r} OR={person_or!r} type={event_type!r} range=[{start},{end}]")
    print(f"[Cypher]\n{cypher}")
    try:
        results = run_query(cypher)
        events = [
            {"id": r["id"], "title": r["title"], "year": r["year"],
             "desc": r["desc"], "source_text": r["source_text"], "type": r["type"],
             "locations": [x for x in r["locations"] if x]}
            for r in results
        ]
        print(f"[Result] {len(events)} events returned")
        return {"events": events}
    except Exception as err:
        print(f"[Query error] {err}")
        return {"events": []}



@app.get("/api/filter-meta")
async def api_filter_meta():
    """返回用于过滤器的元数据：地点列表、事件类型列表"""
    try:
        locs_result = run_query("MATCH (l:Location) WHERE l.name IS NOT NULL RETURN DISTINCT l.name AS n ORDER BY n LIMIT 200")
        locations = [r["n"] for r in locs_result]
        types_result = run_query("MATCH (e:Event) WHERE e.type IS NOT NULL AND e.type <> '' RETURN DISTINCT e.type AS t ORDER BY t")
        event_types = [r["t"] for r in types_result]
        return {"locations": locations, "event_types": event_types}
    except Exception as err:
        print(f"Meta error: {err}")
        return {"locations": [], "event_types": []}

@app.get("/api/persons")
async def api_persons():
    """返回所有历史人物名称（用于前端文本中的人名识别与高亮）"""
    try:
        results = run_query("MATCH (p:Person) WHERE p.name IS NOT NULL RETURN DISTINCT p.name AS name ORDER BY name")
        return {"persons": [r["name"] for r in results]}
    except Exception as err:
        return {"persons": []}

@app.get("/api/person/{name}")
async def api_person_timeline(name: str):
    """返回某人物一生的所有事件，按年份排序，用于时间尺人物轨迹展示"""
    cypher = """
    MATCH (p:Person)-[:PARTICIPATED_IN]->(e:Event)
    WHERE p.name = $name AND e.std_start_year IS NOT NULL
    RETURN e.title AS title, e.std_start_year AS year, e.description AS desc
    ORDER BY e.std_start_year ASC
    """
    try:
        results = run_query(cypher, {"name": name})
        events = [{"title": r["title"], "year": r["year"], "desc": r["desc"]} for r in results]
        return {"name": name, "events": events}
    except Exception as err:
        print(f"Person query error: {err}")
        return {"name": name, "events": []}



@app.get("/api/graph")
async def api_graph(limit: int = 150):
    # 返回图谱的核心节点用于前端可视化展示 (Force Graph)
    # 为防止前端卡顿，限制查询的数据量
    cypher = f"""
    MATCH (p:Person)-[r:PARTICIPATED_IN]->(e:Event)
    RETURN p.name AS person, e.title AS event, e.type AS type
    LIMIT {limit}
    """
    try:
        results = run_query(cypher)
    except Exception as err:
        return {"nodes": [], "links": []}
    
    nodes = []
    links = []
    added_nodes = set()
    
    for row in results:
        p_name = row['person']
        e_name = row['event']
        
        if p_name not in added_nodes:
            nodes.append({"id": p_name, "group": 1, "label": p_name})
            added_nodes.add(p_name)
            
        if e_name not in added_nodes:
            nodes.append({"id": e_name, "group": 2, "label": e_name})
            added_nodes.add(e_name)
            
        links.append({"source": p_name, "target": e_name})
        
    return {"nodes": nodes, "links": links}

if __name__ == "__main__":
    print("🚀 正在启动三国历史数字地图 API 服务...")
    print("请在浏览器中打开: http://127.0.0.1:8000")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
