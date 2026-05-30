import os
# 解决国内服务器加载 Hugging Face 模型报错：在任何第三方库载入前，自动读取并加载 .env 文件中的镜像配置 (如 HF_ENDPOINT)
# 使用 __file__ 的绝对路径定位，确保无论在哪个目录下运行 python3 server.py，都能精准读取到根目录下的 .env 文件
_base_dir = os.path.dirname(os.path.abspath(__file__))
_env_path = os.path.join(_base_dir, ".env")
if os.path.exists(_env_path):
    with open(_env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

import json
import uvicorn
from functools import lru_cache
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from agent.qa_agent import ask_question
from agent.graph_client import run_query

# === 本地向量数据库 (ChromaDB) 与 BGE-M3 模型初始化 ===
import chromadb
from scripts.build_vector_db import LocalBgem3EmbeddingFunction

print("🚀 正在加载本地向量数据库与预热 BGE-M3 模型...")
chroma_client = chromadb.PersistentClient(path="data/chroma_db")
bgem3_ef = LocalBgem3EmbeddingFunction()

# 预热模型：触发延迟加载，使 2.27 GB 权重一次性载入并常驻内存
try:
    bgem3_ef(["预热"])
    print("✅ BGE-M3 向量模型已成功常驻内存，检索服务就绪！")
except Exception as e:
    print(f"⚠️ 模型预热失败 ({str(e)})，可能由于尚未下载模型权重或设备配置问题。")

chroma_collection = chroma_client.get_collection(
    name="sanguozhi_events_bgem3",
    embedding_function=bgem3_ef
)

app = FastAPI(title="Sanguozhi Map API")

# Add CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SearchRequest(BaseModel):
    query: str
    n_results: int = 3

class AskRequest(BaseModel):
    question: str

class FeedbackRequest(BaseModel):
    event_id: str
    event_title: str
    field_name: str
    proposed_value: str

class AdminDeleteRequest(BaseModel):
    ids: list[int]

class AdminApplyItem(BaseModel):
    id: int
    event_id: str
    field_name: str
    proposed_value: str

class AdminApplyRequest(BaseModel):
    items: list[AdminApplyItem]

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


ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "sanguo123")

def verify_admin_password(x_admin_password: str = Header(None)):
    if not x_admin_password or x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(
            status_code=401,
            detail="密码错误，军师请重新输入。"
        )

@app.get("/api/admin/feedback")
async def get_admin_feedback(x_admin_password: str = Header(None)):
    verify_admin_password(x_admin_password)
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "SELECT id, event_id, event_title, field_name, proposed_value, status, created_at FROM feedback WHERE status = 'pending' ORDER BY created_at DESC"
            cursor.execute(sql)
            results = cursor.fetchall()
        conn.close()
        for r in results:
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
        return {"success": True, "feedbacks": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/feedback/delete")
async def delete_admin_feedback(req: AdminDeleteRequest, x_admin_password: str = Header(None)):
    verify_admin_password(x_admin_password)
    if not req.ids:
        return {"success": True, "message": "No feedbacks to delete."}
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            format_strings = ','.join(['%s'] * len(req.ids))
            sql = f"DELETE FROM feedback WHERE id IN ({format_strings})"
            cursor.execute(sql, tuple(req.ids))
        conn.commit()
        conn.close()
        return {"success": True, "message": f"Successfully deleted {len(req.ids)} feedback records."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/feedback/apply")
async def apply_admin_feedback(req: AdminApplyRequest, x_admin_password: str = Header(None)):
    verify_admin_password(x_admin_password)
    if not req.items:
        return {"success": True, "message": "No feedbacks to apply."}
    
    success_count = 0
    errors = []
    
    conn = get_db_connection()
    try:
        for item in req.items:
            event_id = item.event_id
            field_name = item.field_name
            proposed_value = item.proposed_value.strip()
            
            try:
                # 1. Apply to Neo4j
                if field_name == 'locations':
                    locs = [l.strip() for l in proposed_value.split(',') if l.strip()]
                    # Delete old relationships
                    del_cypher = "MATCH (e:Event {id: $event_id})-[r:HAPPENED_AT]->() DELETE r"
                    run_query(del_cypher, {"event_id": event_id})
                    
                    # Create new relationships
                    for loc in locs:
                        merge_cypher = """
                        MATCH (e:Event {id: $event_id})
                        MERGE (l:Location {name: $loc})
                        MERGE (e)-[:HAPPENED_AT]->(l)
                        """
                        run_query(merge_cypher, {"event_id": event_id, "loc": loc})
                        
                elif field_name in ('std_start_year', 'year'):
                    try:
                        val = int(proposed_value)
                    except ValueError:
                        val = proposed_value
                    
                    set_cypher = "MATCH (e:Event {id: $event_id}) SET e.std_start_year = $val"
                    run_query(set_cypher, {"event_id": event_id, "val": val})
                else:
                    target_field = "description" if field_name == "desc" else field_name
                    set_cypher = f"MATCH (e:Event {{id: $event_id}}) SET e.{target_field} = $val"
                    run_query(set_cypher, {"event_id": event_id, "val": proposed_value})
                
                # 2. Update status in MySQL to 'approved'
                with conn.cursor() as cursor:
                    sql = "UPDATE feedback SET status = 'approved', proposed_value = %s WHERE id = %s"
                    cursor.execute(sql, (proposed_value, item.id))
                conn.commit()
                success_count += 1
                
            except Exception as item_err:
                errors.append(f"Feedback ID {item.id} failed: {str(item_err)}")
                
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))
        
    conn.close()
    
    return {
        "success": len(errors) == 0,
        "applied_count": success_count,
        "errors": errors,
        "message": f"Successfully applied {success_count} feedbacks. Errors: {len(errors)}"
    }

@app.post("/api/ask")
async def api_ask(req: AskRequest):
    # 调用大模型与图数据库交互
    answer = ask_question(req.question)
    return {"answer": answer}

@app.post("/api/semantic-search")
async def api_semantic_search(req: SearchRequest):
    """
    语义检索接口：使用常驻内存的 BGE-M3 模型，在毫秒级内完成语义搜索与召回
    """
    try:
        print(f"\n[Semantic Search] 正在检索: '{req.query}' (N={req.n_results})")
        results = chroma_collection.query(
            query_texts=[req.query],
            n_results=req.n_results
        )
        
        # 格式化组装结果返回给前端
        formatted_results = []
        if results and results.get('documents') and len(results['documents']) > 0:
            for doc, meta in zip(results['documents'][0], results['metadatas'][0]):
                formatted_results.append({
                    "person_name": meta.get("person_name", "未知"),
                    "title": meta.get("title", "无标题"),
                    "document": doc,
                    "metadata": meta
                })
        
        print(f"[Semantic Search] 检索完成，成功召回 {len(formatted_results)} 条记录")
        return {"success": True, "results": formatted_results}
    except Exception as e:
        print(f"[Semantic Search Error] {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/events")
async def api_events(
    start: int, end: int,
    person_include: str = "",
    person_or: str = "",
    person_exclude: str = "",
    location: str = "",
    event_type: str = "",
    limit: int = 100,
    offset: int = 0,
):
    safe_limit = max(1, min(limit, 100))
    safe_offset = max(0, offset)
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
    ORDER BY e.std_start_year ASC, e.seq_index ASC, e.id ASC
    SKIP {safe_offset}
    LIMIT {safe_limit}
    """
    print(f"\n{'='*60}")
    print(f"[/api/events] AND={person_include!r} OR={person_or!r} type={event_type!r} range=[{start},{end}] offset={safe_offset} limit={safe_limit}")
    print(f"[Cypher]\n{cypher}")
    try:
        results = run_query(cypher)
        events = serialize_event_rows(results)
        print(f"[Result] {len(events)} events returned")
        return {"events": events, "has_more": len(events) == safe_limit, "offset": safe_offset, "limit": safe_limit}
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


@app.get("/api/events/{event_id}")
async def api_event_detail(event_id: str):
    cypher = """
    MATCH (e:Event {id: $event_id})
    OPTIONAL MATCH (e)-[:HAPPENED_AT]->(l:Location)
    WITH e, collect(DISTINCT l.name) AS locations
    RETURN e.id AS id, e.title AS title, e.std_start_year AS year,
           e.description AS desc, e.source_text AS source_text, e.type AS type, locations
    LIMIT 1
    """
    try:
        results = run_query(cypher, {"event_id": event_id})
        events = serialize_event_rows(results)
        return {"event": events[0] if events else None}
    except Exception as err:
        print(f"Event detail query error: {err}")
        return {"event": None}



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
    """返回与指定人物共同参与过事件的人物关系列表，以及静态地缘、世族、世系图谱数据。"""
    # 1. 查找静态籍贯与世族
    profile_cypher = """
    MATCH (center:Person {name: $name})
    OPTIONAL MATCH (center)-[:HOMETOWN]->(h:Location)
    OPTIONAL MATCH (center)-[:MEMBER_OF]->(c:Clan)
    RETURN h.name AS hometown, c.name AS clan
    LIMIT 1
    """
    
    # 2. 查找静态社交圈关系
    static_relations_cypher = """
    MATCH (center:Person {name: $name})
    MATCH (center)-[r:KINSHIP|ALLY|ENEMY|RULER_SUBJECT|RECOMMENDED]->(other:Person)
    RETURN other.name AS person, type(r) AS rel_type, r.desc AS desc, 'outgoing' AS dir
    
    UNION
    
    MATCH (center:Person {name: $name})
    MATCH (center)<-[r:KINSHIP|ALLY|ENEMY|RULER_SUBJECT|RECOMMENDED]-(other:Person)
    RETURN other.name AS person, type(r) AS rel_type, r.desc AS desc, 'incoming' AS dir
    """
    
    # 3. 查找事件交集 (经典 co-events)
    co_events_cypher = """
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
        # 执行查询
        profile_res = run_query(profile_cypher, {"name": name})
        hometown = profile_res[0]["hometown"] if profile_res and profile_res[0]["hometown"] else None
        clan = profile_res[0]["clan"] if profile_res and profile_res[0]["clan"] else None
        
        static_res = run_query(static_relations_cypher, {"name": name})
        co_events_res = run_query(co_events_cypher, {"name": name, "limit": max(1, min(limit, 200))})
        
        # 兼容旧列表
        relations = [
            {
                "person": r["person"],
                "count": r["count"],
                "events": [event for event in r["events"] if event.get("title")],
            }
            for r in co_events_res
        ]
        
        # 构建图谱节点与连边 (脑图数据)
        nodes = [{"id": name, "label": name, "type": "center"}]
        links = []
        added_nodes = {name}
        
        if hometown:
            nodes.append({"id": hometown, "label": hometown, "type": "hometown"})
            links.append({"source": name, "target": hometown, "type": "HOMETOWN", "desc": "籍贯"})
            added_nodes.add(hometown)
            
        if clan:
            nodes.append({"id": clan, "label": clan, "type": "clan"})
            links.append({"source": name, "target": clan, "type": "MEMBER_OF", "desc": "世族"})
            added_nodes.add(clan)
            
        # 添加静态网络
        for row in static_res:
            p_name = row["person"]
            rel_type = row["rel_type"]
            desc = row["desc"]
            
            if p_name not in added_nodes:
                nodes.append({"id": p_name, "label": p_name, "type": "person"})
                added_nodes.add(p_name)
                
            if row["dir"] == "outgoing":
                links.append({"source": name, "target": p_name, "type": rel_type, "desc": desc})
            else:
                links.append({"source": p_name, "target": name, "type": rel_type, "desc": desc})
                
        # 挑选事件交集前 12 名融合进图谱连边，作为动态关联的展现
        for r in relations[:12]:
            p_name = r["person"]
            if p_name not in added_nodes:
                nodes.append({"id": p_name, "label": p_name, "type": "person"})
                added_nodes.add(p_name)
                links.append({"source": name, "target": p_name, "type": "CO_EVENT", "desc": f"共事{r['count']}次"})
                
        return {
            "name": name,
            "hometown": hometown,
            "clan": clan,
            "nodes": nodes,
            "links": links,
            "relations": relations
        }
    except Exception as err:
        print(f"Person relations query error: {err}")
        return {
            "name": name,
            "hometown": None,
            "clan": None,
            "nodes": [{"id": name, "label": name, "type": "center"}],
            "links": [],
            "relations": []
        }



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
