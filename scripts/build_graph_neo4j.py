import os
import json
import glob
import re
import hashlib
import sys
from neo4j import GraphDatabase

def generate_id(text: str) -> str:
    """用MD5为事件生成唯一图谱节点ID"""
    return hashlib.md5(text.encode('utf-8')).hexdigest()[:8]

def clean_locations_fallback(loc_str: str):
    """降级处理：简单按照标点分割地名"""
    if not loc_str or "不详" in loc_str:
        return []
    parts = re.split(r'[、/，,]', loc_str)
    return [p.strip() for p in parts if p.strip()]

def load_geo_dictionary():
    """加载东汉标准地理行政区划字典（含经纬度、类型、现代地名对应等）"""
    geo_dict = {}
    path = "data/eastern_han_admin.json"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for prov in data.get("provinces", []):
                prov_id = prov["id"]
                geo_dict[prov_id] = {
                    "name": prov["name"],
                    "level": "State",
                    "lat": prov.get("center", {}).get("lat"),
                    "lng": prov.get("center", {}).get("lng"),
                    "type": "州",
                    "region": prov["name"]
                }
                for cmd in prov.get("commanderies", []):
                    cmd_id = cmd["id"]
                    geo_dict[cmd_id] = {
                        "name": cmd["name"],
                        "level": "Commandery",
                        "lat": cmd.get("center", {}).get("lat"),
                        "lng": cmd.get("center", {}).get("lng"),
                        "type": cmd.get("type", "郡"),
                        "region": f"{prov['name']}-{cmd['name']}"
                    }
                    for county in cmd.get("counties", []):
                        county_id = county["id"]
                        geo_dict[county_id] = {
                            "name": county["name"],
                            "level": "County",
                            "lat": county.get("lat"),
                            "lng": county.get("lng"),
                            "type": county.get("type", "县"),
                            "region": county.get("region", f"{prov['name']}-{cmd['name']}"),
                            "modern": county.get("modern")
                        }
            print(f"📖 成功加载东汉地理行政区划，包含 {len(geo_dict)} 个地理节点属性。")
        except Exception as e:
            print(f"⚠️ 读取地理行政区划失败: {e}")
    return geo_dict


def load_groups_dictionary():
    """加载利益集团与世家大族数据"""
    groups_dict = {}
    path = "data/sanguo_groups_clans.json"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 加载 political_factions
                for fct in data.get("political_factions", []):
                    groups_dict[fct["id"]] = {
                        "name": fct["name"],
                        "description": fct.get("description", ""),
                        "origin": fct.get("origin", ""),
                        "ancestral_home": "",
                        "surname": "",
                        "representatives": fct.get("representatives", [])
                    }
                # 加载 great_clans
                for clan in data.get("great_clans", []):
                    groups_dict[clan["id"]] = {
                        "name": clan["name"],
                        "description": clan.get("description", ""),
                        "origin": "",
                        "ancestral_home": clan.get("ancestral_home", ""),
                        "surname": clan.get("surname", ""),
                        "representatives": clan.get("representatives", [])
                    }
            print(f"📖 成功加载集团词典，包含 {len(groups_dict)} 个势力/世家。")
        except Exception as e:
            print(f"⚠️ 读取集团词典失败: {e}")
    return groups_dict

def load_major_events_dictionary():
    """加载重大历史事件数据"""
    me_dict = {}
    path = "data/sanguo_events.json"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for ev in data.get("events", []):
                    me_dict[ev["id"]] = {
                        "title": ev["title"],
                        "year": ev.get("year"),
                        "location_name": ev.get("location", {}).get("name", ""),
                        "location_region": ev.get("location", {}).get("region", ""),
                        "location_desc": ev.get("location", {}).get("description", ""),
                        "characters": ev.get("characters", []),
                        "description": ev.get("description", "")
                    }
            print(f"📖 成功加载重大事件词典，包含 {len(me_dict)} 条历史事件。")
        except Exception as e:
            print(f"⚠️ 读取重大事件词典失败: {e}")
    return me_dict



def build_cypher_queries(json_file_path, groups_dict, me_dict, geo_dict):
    file_name = os.path.basename(json_file_path)
    chapter_name = file_name.replace("_events.json", "")
    
    with open(json_file_path, "r", encoding="utf-8") as f:
        events = json.load(f)
        
    queries = []
    
    for idx, e in enumerate(events):
        original_text = e.get("原文", "")
        if not original_text:
            continue
            
        # 产生事件唯一ID
        event_id = f"evt_{generate_id(original_text)}"
        
        # 清浅转义属性，防止 Cypher 语法崩溃
        event_title = e.get("事件标题", "").replace('\\', '\\\\').replace("'", r"\'")
        time_text = e.get("时间", "").replace('\\', '\\\\').replace("'", r"\'")
        location_text = e.get("地点", "").replace('\\', '\\\\').replace("'", r"\'")
        source_text = original_text.replace('\\\\', '\\\\\\\\').replace("'", r"\'")
        translation = e.get("事件翻译", "").replace('\\\\', '\\\\\\\\').replace("'", r"\'")
        is_main_biography = e.get("是否本传", e.get("is_main_biography", False))
        is_main_biography_str = "true" if is_main_biography else "false"
        
        std_start_year = e.get("std_start_year")
        std_start_year_str = str(std_start_year) if std_start_year is not None else "null"
        
        queries.append(
            f"MERGE (e:Event {{id: '{event_id}'}}) "
            f"SET e.title = '{event_title}', "
            f"e.time_text = '{time_text}', "
            f"e.location_text = '{location_text}', "
            f"e.source_text = '{source_text}', "
            f"e.translation = '{translation}', "
            f"e.std_start_year = {std_start_year_str}, "
            f"e.is_main_biography = {is_main_biography_str}, "
            f"e.seq_index = {idx}, "
            f"e.protagonist = '{chapter_name}', "
            f"e.chapter = '{chapter_name}';"
        )
        
        # 2. 人物实体及参与关系
        characters = e.get("相关人物", [])
        for char in characters:
            char_escaped = char.replace("'", r"\'")
            queries.append(f"MERGE (p:Person {{name: '{char_escaped}'}});")
            queries.append(
                f"MATCH (p:Person {{name: '{char_escaped}'}}), (e:Event {{id: '{event_id}'}}) "
                f"MERGE (p)-[:PARTICIPATED_IN]->(e);"
            )
            
        # 3. 涉及的集团/世家及关联关系
        groups = e.get("涉及的集团", [])
        for gid in groups:
            g_info = groups_dict.get(gid, {
                "name": gid,
                "description": "",
                "origin": "",
                "ancestral_home": "",
                "surname": "",
                "representatives": []
            })
            g_name = g_info["name"].replace("'", r"\'")
            g_desc = g_info["description"].replace('\\', '\\\\').replace("'", r"\'")
            
            g_origin = g_info.get("origin", "").replace("'", r"\'")
            g_home = g_info.get("ancestral_home", "").replace("'", r"\'")
            g_surname = g_info.get("surname", "").replace("'", r"\'")
            
            g_reps = g_info.get("representatives", [])
            g_rep_names = [rep.get("name", "") for rep in g_reps if rep.get("name")]
            g_reps_escaped = ["'" + name.replace("'", r"\'") + "'" for name in g_rep_names]
            g_reps_str = "[" + ", ".join(g_reps_escaped) + "]"
            
            queries.append(
                f"MERGE (g:Group {{id: '{gid}'}}) "
                f"SET g.name = '{g_name}', "
                f"g.description = '{g_desc}', "
                f"g.origin = '{g_origin}', "
                f"g.ancestral_home = '{g_home}', "
                f"g.surname = '{g_surname}', "
                f"g.representatives = {g_reps_str};"
            )
            queries.append(
                f"MATCH (e:Event {{id: '{event_id}'}}), (g:Group {{id: '{gid}'}}) "
                f"MERGE (e)-[:INVOLVES_GROUP]->(g);"
            )
            
            # 建立代表和Group的关系
            for rep in g_reps:
                rep_name = rep.get("name")
                if not rep_name:
                    continue
                rep_name_esc = rep_name.replace("'", r"\'")
                rep_alias = rep.get("alias")
                rep_alias_esc = rep_alias.replace("'", r"\'") if rep_alias else ""
                rep_faction = rep.get("faction")
                rep_faction_esc = rep_faction.replace("'", r"\'") if rep_faction else ""
                rep_desc = rep.get("description")
                rep_desc_esc = rep_desc.replace('\\', '\\\\').replace("'", r"\'") if rep_desc else ""
                
                queries.append(
                    f"MERGE (p:Person {{name: '{rep_name_esc}'}}) "
                    f"SET p.alias = '{rep_alias_esc}', "
                    f"p.faction = '{rep_faction_esc}', "
                    f"p.description = '{rep_desc_esc}';"
                )
                queries.append(
                    f"MATCH (p:Person {{name: '{rep_name_esc}'}}), (g:Group {{id: '{gid}'}}) "
                    f"MERGE (p)-[:REPRESENTATIVE_OF]->(g);"
                )
            
        # 4. 所属重大历史事件
        major_events = e.get("所属事件", [])
        for me_id in major_events:
            me_info = me_dict.get(me_id, {
                "title": me_id,
                "year": None,
                "location_name": "",
                "location_region": "",
                "location_desc": "",
                "characters": [],
                "description": ""
            })
            me_title = me_info["title"].replace("'", r"\'")
            me_desc = me_info["description"].replace('\\', '\\\\').replace("'", r"\'")
            
            me_year = me_info.get("year")
            me_year_str = str(me_year) if me_year is not None else "null"
            
            me_loc_name = me_info.get("location_name", "").replace("'", r"\'")
            me_loc_region = me_info.get("location_region", "").replace("'", r"\'")
            me_loc_desc = me_info.get("location_desc", "").replace("'", r"\'")
            
            me_chars = me_info.get("characters", [])
            me_chars_escaped = ["'" + c.replace("'", r"\'") + "'" for c in me_chars]
            me_chars_str = "[" + ", ".join(me_chars_escaped) + "]"
            
            queries.append(
                f"MERGE (me:MajorEvent {{id: '{me_id}'}}) "
                f"SET me.title = '{me_title}', "
                f"me.description = '{me_desc}', "
                f"me.year = {me_year_str}, "
                f"me.location_name = '{me_loc_name}', "
                f"me.location_region = '{me_loc_region}', "
                f"me.location_desc = '{me_loc_desc}', "
                f"me.characters = {me_chars_str};"
            )
            queries.append(
                f"MATCH (e:Event {{id: '{event_id}'}}), (me:MajorEvent {{id: '{me_id}'}}) "
                f"MERGE (e)-[:BELONGS_TO_MAJOR]->(me);"
            )
            
            # 建立 MajorEvent 与 Person 的关联
            for char in me_chars:
                char_escaped = char.replace("'", r"\'")
                queries.append(f"MERGE (p:Person {{name: '{char_escaped}'}});")
                queries.append(
                    f"MATCH (p:Person {{name: '{char_escaped}'}}), (me:MajorEvent {{id: '{me_id}'}}) "
                    f"MERGE (p)-[:PARTICIPATED_IN]->(me);"
                )
                
            # 建立 MajorEvent 与 Location 的关联
            if me_loc_name:
                me_loc_name_esc = me_loc_name.replace("'", r"\'")
                queries.append(
                    f"MERGE (l:Location {{name: '{me_loc_name_esc}'}}) "
                    f"SET l.region = '{me_loc_region}', "
                    f"l.description = '{me_loc_desc}';"
                )
                queries.append(
                    f"MATCH (me:MajorEvent {{id: '{me_id}'}}), (l:Location {{name: '{me_loc_name_esc}'}}) "
                    f"MERGE (me)-[:HAPPENED_AT]->(l);"
                )
            
        # 5. 标准地理空间解析：从地理区划字典中提取富文本属性
        geography_list = e.get("地理信息", [])
        if geography_list:
            for geo_path in geography_list:
                parts = geo_path.split(":")
                
                # 构建逐级 ID：比如 ["交州", "交州:郁林郡", "交州:郁林郡:右江"]
                current_path_ids = []
                for i in range(len(parts)):
                    current_path_ids.append(":".join(parts[:i+1]))
                
                prev_node_name = None
                for i, geo_id in enumerate(current_path_ids):
                    geo_info = geo_dict.get(geo_id)
                    if geo_info:
                        loc_name = geo_info["name"].replace("'", r"\'")
                        loc_level = geo_info["level"]
                        loc_type = geo_info.get("type", "").replace("'", r"\'")
                        loc_region = geo_info.get("region", "").replace("'", r"\'")
                        loc_modern = geo_info.get("modern")
                        if loc_modern:
                            loc_modern_escaped = loc_modern.replace("'", r"\'")
                            loc_modern_str = f"'{loc_modern_escaped}'"
                        else:
                            loc_modern_str = "null"
                        
                        lat = geo_info.get("lat")
                        lng = geo_info.get("lng")
                        lat_str = str(lat) if lat is not None else "null"
                        lng_str = str(lng) if lng is not None else "null"
                    else:
                        # 降级容错
                        loc_name = parts[i].replace("'", r"\'")
                        loc_level = ["State", "Commandery", "County"][i] if i < 3 else "Subcounty"
                        loc_type = "未识"
                        loc_region = ""
                        loc_modern_str = "null"
                        lat_str = "null"
                        lng_str = "null"
                        
                    # 创建地理节点，补充经纬度坐标、建制类型、现代地名及区域归属
                    queries.append(
                        f"MERGE (l:Location {{name: '{loc_name}'}}) "
                        f"SET l.level = '{loc_level}', "
                        f"l.type = '{loc_type}', "
                        f"l.region = '{loc_region}', "
                        f"l.modern = {loc_modern_str}, "
                        f"l.lat = {lat_str}, "
                        f"l.lng = {lng_str};"
                    )
                    
                    if prev_node_name:
                        queries.append(
                            f"MATCH (child:Location {{name: '{loc_name}'}}), (parent:Location {{name: '{prev_node_name}'}}) "
                            f"MERGE (child)-[:BELONGS_TO]->(parent);"
                        )
                    prev_node_name = loc_name
                
                # 将事件关联到最具体的地理位置上（即路径的最末端）
                leaf_loc = parts[-1].replace("'", r"\'")
                queries.append(
                    f"MATCH (e:Event {{id: '{event_id}'}}), (l:Location {{name: '{leaf_loc}'}}) "
                    f"MERGE (e)-[:HAPPENED_AT]->(l);"
                )
        else:
            # 降级处理：如果没有标准地理信息，使用普通“地点”字段分割匹配
            fallback_locs = clean_locations_fallback(e.get("地点", ""))
            for loc in fallback_locs:
                loc_escaped = loc.replace("'", r"\'")
                queries.append(f"MERGE (l:Location {{name: '{loc_escaped}'}}) SET l.level = 'Unresolved';")
                queries.append(
                    f"MATCH (e:Event {{id: '{event_id}'}}), (l:Location {{name: '{loc_escaped}'}}) "
                    f"MERGE (e)-[:HAPPENED_AT]->(l);"
                )
                
    return queries

def main():
    groups_dict = load_groups_dictionary()
    me_dict = load_major_events_dictionary()
    geo_dict = load_geo_dictionary()
    
    # 支持命令行参数只导入单卷文件
    target_file = None
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if os.path.exists(arg):
            target_file = arg
        elif os.path.exists(f"data/raw/{arg}"):
            target_file = f"data/raw/{arg}"
        elif os.path.exists(f"data/raw/{arg}_events.json"):
            target_file = f"data/raw/{arg}_events.json"
        else:
            print(f"❌ 找不到指定的文件: {arg}")
            sys.exit(1)
            
    all_queries = []
    
    if target_file:
        chapter_name = os.path.basename(target_file).replace("_events.json", "")
        print(f"ℹ️ 检测到指定导入单卷: {target_file}")
        # 清除该卷的历史节点，防止重复，以便单卷覆盖写入
        all_queries.append(f"MATCH (e:Event {{chapter: '{chapter_name}'}}) DETACH DELETE e;")
        all_json_files = [target_file]
    else:
        print("ℹ️ 未指定单个文件，执行全量导入。")
        # 清空数据库重新灌入
        all_queries.append("MATCH (n) DETACH DELETE n;")
        all_json_files = glob.glob("data/raw/*_events.json")
        
    for idx, fpath in enumerate(all_json_files):
        print(f"[{idx+1}/{len(all_json_files)}] 📂 正在抽象文件: {os.path.basename(fpath)}")
        all_queries.extend(build_cypher_queries(fpath, groups_dict, me_dict, geo_dict))
        
    print(f"\n✅ 成功生成图谱 Cypher 语句，共 {len(all_queries)} 条。")
    print("准备将数据灌入本地 Neo4j 数据库...")
    
    pwd = "12345678"  # 根据你的本地 Neo4j 密码修改
    try:
        driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", pwd))
        driver.verify_connectivity()
        print("✅ 成功连接到 Neo4j 数据库！")
        
        # 1. 确保唯一性约束（自动创建索引）存在，这是提升 MERGE 性能的关键
        print("⚡ 正在创建/确认唯一性约束与索引...")
        constraints = {
            "Event(id)": "CREATE CONSTRAINT event_id_unique IF NOT EXISTS FOR (e:Event) REQUIRE e.id IS UNIQUE;",
            "Person(name)": "CREATE CONSTRAINT person_name_unique IF NOT EXISTS FOR (p:Person) REQUIRE p.name IS UNIQUE;",
            "Group(id)": "CREATE CONSTRAINT group_id_unique IF NOT EXISTS FOR (g:Group) REQUIRE g.id IS UNIQUE;",
            "MajorEvent(id)": "CREATE CONSTRAINT major_event_id_unique IF NOT EXISTS FOR (me:MajorEvent) REQUIRE me.id IS UNIQUE;",
            "Location(name)": "CREATE CONSTRAINT location_name_unique IF NOT EXISTS FOR (l:Location) REQUIRE l.name IS UNIQUE;"
        }
        
        with driver.session() as session:
            for label, c in constraints.items():
                print(f"  - 正在检查 {label} 唯一性约束...", end="", flush=True)
                try:
                    session.run(c)
                    print(" [OK]")
                except Exception as ce:
                    # 针对旧版本 Neo4j 的约束语法降级兼容
                    try:
                        m = re.search(r'FOR \((e|p|g|me|l):(\w+)\) REQUIRE \1\.(\w+) IS UNIQUE', c)
                        if m:
                            label_name, prop = m.group(2), m.group(3)
                            old_syntax = f"CREATE CONSTRAINT ON (n:{label_name}) ASSERT n.{prop} IS UNIQUE"
                            session.run(old_syntax)
                            print(" [OK (旧语法)]")
                        else:
                            print(" [已跳过]")
                    except Exception:
                        print(" [已跳过]")
                        
        print("✅ 唯一性约束与索引确认完毕，开始批量写入数据...")
        
        # 2. 分批事务写入，彻底解决一条条提交的网络和磁盘 I/O 瓶颈
        batch_size = 2000
        total_batches = (len(all_queries) + batch_size - 1) // batch_size
        with driver.session() as session:
            for i in range(0, len(all_queries), batch_size):
                batch = all_queries[i:i+batch_size]
                batch_num = i // batch_size + 1
                try:
                    with session.begin_transaction() as tx:
                        for q in batch:
                            tx.run(q)
                    print(f"  🚀 [批次 {batch_num}/{total_batches}] 已成功写入 {min(i + batch_size, len(all_queries))}/{len(all_queries)} 条 Cypher 语句...")
                except Exception as tx_err:
                    print(f"  ❌ [批次 {batch_num}/{total_batches}] 写入失败，正在回退为逐条写入以定位错误...")
                    # 如果整批事务失败，降级为逐条执行，防止因单个语法错误导致整批回滚
                    for q in batch:
                        try:
                            session.run(q)
                        except Exception as single_err:
                            print(f"    ⚠️ 语句执行失败: {q}\n    错误原因: {single_err}")
                
        print(f"🎉 成功导入全部 {len(all_queries)} 条 cypher 语句，图谱构建完成！")
        print("现在可以在浏览器访问 http://localhost:7474 查看可视化关联图谱。")
        driver.close()
    except Exception as e:
        print(f"❌ 数据库连接或写入失败: {e}")

if __name__ == "__main__":
    main()
