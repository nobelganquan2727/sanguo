import os
import json
import uvicorn
from functools import lru_cache
from pathlib import Path
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


ADMIN_GEO_PATH = Path(__file__).resolve().parent / "frontend" / "public" / "eastern_han_admin.json"


@lru_cache(maxsize=1)
def load_admin_geo():
    with ADMIN_GEO_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def expand_location_names(name: str, level: str, province: str = "", commandery: str = "") -> list[str]:
    """Expand province/commandery clicks to descendant commandery/county names."""
    names: set[str] = {name}
    admin_geo = load_admin_geo()

    for province_node in admin_geo.get("provinces", []):
        if level == "province" and province_node.get("name") != name:
            continue
        if level != "province" and province and province_node.get("name") != province:
            continue

        for commandery_node in province_node.get("commanderies", []):
            if level == "commandery" and commandery_node.get("name") != name:
                continue
            if level == "county" and commandery and commandery_node.get("name") != commandery:
                continue

            if level in {"province", "commandery"}:
                names.add(commandery_node.get("name", ""))

            for county_node in commandery_node.get("counties", []):
                county_name = county_node.get("name", "")
                if level == "county" and county_name != name:
                    continue

                names.add(county_name)
                for alias in county_node.get("aliases", []):
                    if alias:
                        names.add(alias)

            if level == "commandery":
                break

        if level in {"province", "commandery", "county"} and (level == "province" or province_node.get("name") == province):
            break

    return sorted(n for n in names if n)


def serialize_event_rows(results: list[dict]) -> list[dict]:
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "year": r["year"],
            "desc": r["desc"],
            "source_text": r["source_text"],
            "type": r["type"],
            "locations": [x for x in r["locations"] if x],
            **({"matched_locations": [x for x in r.get("matched_locations", []) if x]} if "matched_locations" in r else {}),
        }
        for r in results
    ]

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
        events = serialize_event_rows(results)
        print(f"[Result] {len(events)} events returned")
        return {"events": events}
    except Exception as err:
        print(f"[Query error] {err}")
        return {"events": []}


@app.get("/api/location-events")
async def api_location_events(
    name: str,
    level: str = "county",
    province: str = "",
    commandery: str = "",
    start: int = 180,
    end: int = 280,
    limit: int = 500,
):
    location_names = expand_location_names(name, level, province, commandery)
    cypher = """
    MATCH (e:Event)-[:HAPPENED_AT]->(matched:Location)
    WHERE matched.name IN $location_names
      AND (e.std_start_year IS NULL OR (e.std_start_year >= $start AND e.std_start_year <= $end))
    WITH DISTINCT e, collect(DISTINCT matched.name) AS matched_locations
    OPTIONAL MATCH (e)-[:HAPPENED_AT]->(l:Location)
    WITH e, matched_locations, collect(DISTINCT l.name) AS locations
    RETURN e.id AS id, e.title AS title, e.std_start_year AS year,
           e.description AS desc, e.source_text AS source_text, e.type AS type,
           locations, matched_locations
    ORDER BY e.std_start_year ASC
    LIMIT $limit
    """
    print(f"\n{'='*60}")
    print(f"[/api/location-events] name={name!r} level={level!r} expanded={len(location_names)}")
    try:
        results = run_query(
            cypher,
            {
                "location_names": location_names,
                "start": start,
                "end": end,
                "limit": max(1, min(limit, 1000)),
            },
        )
        events = serialize_event_rows(results)
        print(f"[Result] {len(events)} events returned")
        return {"location": name, "level": level, "expanded_locations": location_names, "events": events}
    except Exception as err:
        print(f"[Location query error] {err}")
        return {"location": name, "level": level, "expanded_locations": location_names, "events": []}



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


@app.get("/api/person-relations/{name}")
async def api_person_relations(name: str, limit: int = 80):
    """返回与指定人物共同参与过事件的人物关系列表。"""
    cypher = """
    MATCH (center:Person {name: $name})-[:PARTICIPATED_IN]->(e:Event)<-[:PARTICIPATED_IN]-(other:Person)
    WHERE other.name <> center.name
    WITH other, e
    ORDER BY e.std_start_year ASC
    WITH other.name AS person,
         collect(DISTINCT {
           id: e.id,
           title: e.title,
           year: e.std_start_year,
           type: e.type
         }) AS events
    RETURN person, events, size(events) AS count
    ORDER BY count DESC, person ASC
    LIMIT $limit
    """
    try:
        results = run_query(cypher, {"name": name, "limit": max(1, min(limit, 200))})
        relations = [
            {
                "person": r["person"],
                "count": r["count"],
                "events": [event for event in r["events"] if event.get("title")],
            }
            for r in results
        ]
        return {"name": name, "relations": relations}
    except Exception as err:
        print(f"Person relations query error: {err}")
        return {"name": name, "relations": []}



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
