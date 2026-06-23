import json
from pathlib import Path
from functools import lru_cache
from db.neo4j import run_query

ADMIN_GEO_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "eastern_han_admin.json"

@lru_cache(maxsize=1)
def load_admin_geo():
    with ADMIN_GEO_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)

def get_eastern_han_admin():
    return load_admin_geo()

def expand_location_names(name: str, level: str, province: str = "", commandery: str = "") -> list[str]:
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
            "translation": r.get("translation", ""),
            "type": r["type"],
            "locations": r.get("locations", []),
            "characters": r.get("characters", []),
            "major_events": r.get("major_events", []),
            "protagonist": r.get("protagonist", ""),
            "is_main_biography": r.get("is_main_biography", False),
            **({"matched_locations": [x for x in r.get("matched_locations", []) if x]} if "matched_locations" in r else {}),
        }
        for r in results
    ]

def check_neo4j_status():
    run_query("RETURN 1 AS val")

def query_events(
    start: int, end: int,
    person_include: str = "",
    person_or: str = "",
    person_exclude: str = "",
    location: str = "",
    event_type: str = "",
    biography_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], bool]:
    safe_limit = 1000 if biography_only else max(1, min(limit, 100))
    safe_offset = max(0, offset)
    
    where_clauses = []
    
    if biography_only and person_include:
        names = [n.strip() for n in person_include.split(',') if n.strip()]
        if names:
            cond = ' OR '.join([f"(e.protagonist = '{n}' AND e.is_main_biography = true)" for n in names])
            where_clauses.append(f"({cond})")
    else:
        where_clauses.append(
            f"(e.std_start_year IS NULL OR (e.std_start_year >= {start} AND e.std_start_year <= {end}))"
        )
        if person_include:
            names = [n.strip() for n in person_include.split(',') if n.strip()]
            for n in names:
                where_clauses.append(f"EXISTS {{ MATCH (per:Person)-[:PARTICIPATED_IN]->(e) WHERE per.name CONTAINS '{n}' }}")

    if person_or and not (biography_only and person_include):
        names = [n.strip() for n in person_or.split(',') if n.strip()]
        if names:
            cond = ' OR '.join([f"per.name CONTAINS '{n}'" for n in names])
            where_clauses.append(f"EXISTS {{ MATCH (per:Person)-[:PARTICIPATED_IN]->(e) WHERE {cond} }}")

    if person_exclude:
        names = [n.strip() for n in person_exclude.split(',') if n.strip()]
        if names:
            cond = ' OR '.join([f"per.name CONTAINS '{n}'" for n in names])
            where_clauses.append(f"NOT EXISTS {{ MATCH (per:Person)-[:PARTICIPATED_IN]->(e) WHERE {cond} }}")

    if event_type:
        where_clauses.append(f"e.type = '{event_type}'")

    loc_filter = f"WHERE any(loc IN locations WHERE loc.name = '{location}')" if location else ""

    cypher = f"""
    MATCH (e:Event)
    WHERE {' AND '.join(where_clauses)}
    OPTIONAL MATCH (e)-[:HAPPENED_AT]->(l:Location)
    OPTIONAL MATCH (per:Person)-[:PARTICIPATED_IN]->(e)
    OPTIONAL MATCH (e)-[:BELONGS_TO_MAJOR]->(me:MajorEvent)
    WITH e, 
         collect(DISTINCT CASE WHEN l.name IS NOT NULL THEN {{
             name: l.name, 
             lat: l.lat, 
             lng: l.lng, 
             level: l.level, 
             type: l.type, 
             region: l.region, 
             modern: l.modern
         }} ELSE null END) AS locations_raw,
         collect(DISTINCT per.name) AS characters,
         collect(DISTINCT me.id) AS major_events
    WITH e, 
         [x IN locations_raw WHERE x IS NOT NULL] AS locations,
         characters,
         major_events
    {loc_filter}
    RETURN e.id AS id, e.title AS title, e.std_start_year AS year,
           COALESCE(e.translation, e.description) AS desc, e.source_text AS source_text, e.translation AS translation, e.type AS type, 
           locations, characters, major_events, e.protagonist AS protagonist, e.is_main_biography AS is_main_biography
    ORDER BY e.std_start_year ASC, e.seq_index ASC, e.id ASC
    SKIP {safe_offset}
    LIMIT {safe_limit}
    """
    results = run_query(cypher)
    events = serialize_event_rows(results)
    has_more = len(events) == safe_limit if not biography_only else False
    return events, has_more

def query_location_events(
    name: str,
    level: str = "county",
    province: str = "",
    commandery: str = "",
    start: int = 180,
    end: int = 280,
    limit: int = 500,
) -> list[dict]:
    location_names = expand_location_names(name, level, province, commandery)
    cypher = """
    MATCH (e:Event)-[:HAPPENED_AT]->(matched:Location)
    WHERE matched.name IN $location_names
      AND (e.std_start_year IS NULL OR (e.std_start_year >= $start AND e.std_start_year <= $end))
    WITH DISTINCT e, collect(DISTINCT matched.name) AS matched_locations
    OPTIONAL MATCH (e)-[:HAPPENED_AT]->(l:Location)
    OPTIONAL MATCH (per:Person)-[:PARTICIPATED_IN]->(e)
    OPTIONAL MATCH (e)-[:BELONGS_TO_MAJOR]->(me:MajorEvent)
    WITH e, matched_locations,
         collect(DISTINCT CASE WHEN l.name IS NOT NULL THEN {
             name: l.name, 
             lat: l.lat, 
             lng: l.lng, 
             level: l.level, 
             type: l.type, 
             region: l.region, 
             modern: l.modern
         } ELSE null END) AS locations_raw,
         collect(DISTINCT per.name) AS characters,
         collect(DISTINCT me.id) AS major_events
    RETURN e.id AS id, e.title AS title, e.std_start_year AS year,
           COALESCE(e.translation, e.description) AS desc, e.source_text AS source_text, e.translation AS translation, e.type AS type,
           [x IN locations_raw WHERE x IS NOT NULL] AS locations,
           characters, major_events, matched_locations
    ORDER BY e.std_start_year ASC
    LIMIT $limit
    """
    results = run_query(
        cypher,
        {
            "location_names": location_names,
            "start": start,
            "end": end,
            "limit": max(1, min(limit, 1000)),
        },
    )
    return serialize_event_rows(results)

def query_event_detail(event_id: str) -> dict:
    cypher = """
    MATCH (e:Event {id: $event_id})
    OPTIONAL MATCH (e)-[:HAPPENED_AT]->(l:Location)
    OPTIONAL MATCH (per:Person)-[:PARTICIPATED_IN]->(e)
    OPTIONAL MATCH (e)-[:BELONGS_TO_MAJOR]->(me:MajorEvent)
    WITH e,
         collect(DISTINCT CASE WHEN l.name IS NOT NULL THEN {
             name: l.name, 
             lat: l.lat, 
             lng: l.lng, 
             level: l.level, 
             type: l.type, 
             region: l.region, 
             modern: l.modern
         } ELSE null END) AS locations_raw,
         collect(DISTINCT per.name) AS characters,
         collect(DISTINCT me.id) AS major_events
    RETURN e.id AS id, e.title AS title, e.std_start_year AS year,
           COALESCE(e.translation, e.description) AS desc, e.source_text AS source_text, e.translation AS translation, e.type AS type,
           [x IN locations_raw WHERE x IS NOT NULL] AS locations,
           characters, major_events, e.protagonist AS protagonist
    LIMIT 1
    """
    results = run_query(cypher, {"event_id": event_id})
    events = serialize_event_rows(results)
    return events[0] if events else None

def get_filter_meta() -> dict:
    locs_result = run_query("MATCH (l:Location) WHERE l.name IS NOT NULL RETURN DISTINCT l.name AS n ORDER BY n LIMIT 200")
    locations = [r["n"] for r in locs_result]
    types_result = run_query("MATCH (e:Event) WHERE e.type IS NOT NULL AND e.type <> '' RETURN DISTINCT e.type AS t ORDER BY t")
    event_types = [r["t"] for r in types_result]
    return {"locations": locations, "event_types": event_types}

def get_persons_list() -> list[str]:
    results = run_query("MATCH (p:Person) WHERE p.name IS NOT NULL RETURN DISTINCT p.name AS name ORDER BY name")
    return [r["name"] for r in results]

def get_person_timeline(name: str) -> list[dict]:
    cypher = """
    MATCH (p:Person)-[:PARTICIPATED_IN]->(e:Event)
    WHERE p.name = $name AND e.std_start_year IS NOT NULL
    RETURN e.title AS title, e.std_start_year AS year, COALESCE(e.translation, e.description) AS desc
    ORDER BY e.std_start_year ASC
    """
    results = run_query(cypher, {"name": name})
    return [{"title": r["title"], "year": r["year"], "desc": r["desc"]} for r in results]

def get_person_relations(name: str, limit: int = 80) -> dict:
    profile_cypher = """
    MATCH (center:Person {name: $name})
    OPTIONAL MATCH (center)-[:HOMETOWN]->(h:Location)
    OPTIONAL MATCH (center)-[:REPRESENTATIVE_OF]->(g:Group)
    RETURN h.name AS hometown, g.name AS clan
    LIMIT 1
    """
    static_relations_cypher = """
    MATCH (center:Person {name: $name})
    MATCH (center)-[r:KINSHIP|ALLY|ENEMY|RULER_SUBJECT|RECOMMENDED]->(other:Person)
    RETURN other.name AS person, type(r) AS rel_type, r.desc AS desc, 'outgoing' AS dir
    
    UNION
    
    MATCH (center:Person {name: $name})
    MATCH (center)<-[r:KINSHIP|ALLY|ENEMY|RULER_SUBJECT|RECOMMENDED]-(other:Person)
    RETURN other.name AS person, type(r) AS rel_type, r.desc AS desc, 'incoming' AS dir
    """
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
    profile_res = run_query(profile_cypher, {"name": name})
    hometown = profile_res[0]["hometown"] if profile_res and profile_res[0]["hometown"] else None
    clan = profile_res[0]["clan"] if profile_res and profile_res[0]["clan"] else None
    
    static_res = run_query(static_relations_cypher, {"name": name})
    co_events_res = run_query(co_events_cypher, {"name": name, "limit": max(1, min(limit, 200))})
    
    relations = [
        {
            "person": r["person"],
            "count": r["count"],
            "events": [event for event in r["events"] if event.get("title")],
        }
        for r in co_events_res
    ]
    
    nodes = [{"id": name, "label": name, "type": "center"}]
    links = []
    added_nodes = {name}
    
    if hometown:
        nodes.append({"id": hometown, "label": hometown, "type": "hometown"})
        links.append({"source": name, "target": hometown, "type": "HOMETOWN", "desc": "籍贯"})
        added_nodes.add(hometown)
        
    if clan:
        nodes.append({"id": clan, "label": clan, "type": "clan"})
        links.append({"source": name, "target": clan, "type": "REPRESENTATIVE_OF", "desc": "世家/集团"})
        added_nodes.add(clan)
        
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

def get_force_graph(limit: int = 150) -> dict:
    cypher = f"""
    MATCH (p:Person)-[r:PARTICIPATED_IN]->(e:Event)
    RETURN p.name AS person, e.title AS event, e.type AS type
    LIMIT {limit}
    """
    results = run_query(cypher)
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
