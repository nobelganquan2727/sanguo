import json
import os
from pathlib import Path
from neo4j import GraphDatabase

# 加载环境变量
_base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_env_path = os.path.join(_base_dir, ".env")
if os.path.exists(_env_path):
    with open(_env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

def main():
    print("🔄 开始从 Neo4j 备份最新的数据修改并同步回 data/raw/*.json 文件...")
    
    neo4j_pwd = "12345678"
    try:
        driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", neo4j_pwd))
        driver.verify_connectivity()
    except Exception as e:
        print(f"❌ 无法连接到 Neo4j 数据库: {e}")
        return
        
    # 查询所有事件和他们被修改后的属性，包括关联的地点和相关人物
    cypher = """
    MATCH (e:Event)
    OPTIONAL MATCH (e)-[:HAPPENED_AT]->(l:Location)
    OPTIONAL MATCH (p:Person)-[:PARTICIPATED_IN]->(e)
    RETURN e.protagonist AS protagonist, e.seq_index AS seq_index, 
           e.title AS title, e.time_text AS time_text, e.type AS type,
           e.description AS description, e.source_text AS source_text, 
           e.std_start_year AS std_start_year, e.std_end_year AS std_end_year,
           e.is_main_biography AS is_main_biography,
           collect(DISTINCT l.name) AS locations, collect(DISTINCT p.name) AS characters
    """
    
    try:
        with driver.session() as session:
            records = session.run(cypher).data()
    except Exception as e:
        print(f"❌ 从 Neo4j 获取数据失败: {e}")
        driver.close()
        return
        
    driver.close()
    
    if not records:
        print("ℹ️ 图数据库中没有事件数据。")
        return
        
    # 按主角进行分组处理，以防频繁读写同一个文件
    grouped_records = {}
    for r in records:
        protagonist = r["protagonist"]
        if not protagonist:
            continue
        if protagonist not in grouped_records:
            grouped_records[protagonist] = []
        grouped_records[protagonist].append(r)
        
    print(f"📊 从图数据库获取到 {len(records)} 个事件，涉及 {len(grouped_records)} 位主角传记...")
    
    raw_dir = Path(_base_dir) / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    success_files = 0
    updated_events = 0
    new_files = 0
    
    for protagonist, items in grouped_records.items():
        json_path = raw_dir / f"{protagonist}_events.json"
        
        file_updated = False
        if not json_path.exists():
            print(f"➕ [New File] 自动创建缺失的原始 JSON 文件: {json_path}")
            events = []
            file_updated = True
            new_files += 1
        else:
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    events = json.load(f)
            except Exception as e:
                print(f"❌ 读取 JSON 失败 {json_path}: {e}")
                continue
            
        # 区分有序号和无序号的事件
        indexed_items = [item for item in items if item["seq_index"] is not None]
        indexed_items = sorted(indexed_items, key=lambda x: x["seq_index"])
        unindexed_items = [item for item in items if item["seq_index"] is None]
        
        # 对齐列表大小以容纳最大 seq_index
        max_idx = max((item["seq_index"] for item in indexed_items), default=-1)
        while len(events) <= max_idx:
            events.append({})
            file_updated = True
            
        # 处理有序号的事件更新
        for item in indexed_items:
            seq_index = item["seq_index"]
            e = events[seq_index]
            
            # 辅助函数：如果发生变更则设置并记录
            def set_if_changed(key, val):
                nonlocal file_updated
                if e.get(key) != val:
                    e[key] = val
                    file_updated = True

            set_if_changed("事件标题", item["title"] or "")
            set_if_changed("时间", item["time_text"] or "")
            
            locs_str = ",".join(sorted(filter(None, item["locations"])))
            set_if_changed("地点", locs_str)
            
            chars = sorted(filter(None, item["characters"]))
            if e.get("相关人物") != chars:
                e["相关人物"] = chars
                file_updated = True
                
            set_if_changed("事件简介", item["description"] or "")
            set_if_changed("事件类型", item["type"] or "")
            set_if_changed("原文", item["source_text"] or "")
            
            if e.get("std_start_year") != item["std_start_year"]:
                e["std_start_year"] = item["std_start_year"]
                file_updated = True
                
            if e.get("std_end_year") != item["std_end_year"]:
                e["std_end_year"] = item["std_end_year"]
                file_updated = True
                
            is_main = item.get("is_main_biography")
            if is_main is not None and e.get("是否本传") != is_main:
                e["是否本传"] = is_main
                file_updated = True
                
        # 处理没有序号的事件（直接追加）
        for item in unindexed_items:
            new_event = {
                "事件标题": item["title"] or "",
                "时间": item["time_text"] or "",
                "地点": ",".join(sorted(filter(None, item["locations"]))),
                "相关人物": sorted(filter(None, item["characters"])),
                "事件简介": item["description"] or "",
                "事件类型": item["type"] or "",
                "原文": item["source_text"] or "",
                "std_start_year": item["std_start_year"],
                "std_end_year": item["std_end_year"],
                "是否本传": item.get("is_main_biography", False)
            }
            events.append(new_event)
            file_updated = True
            
        if file_updated:
            try:
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(events, f, ensure_ascii=False, indent=2)
                success_files += 1
                updated_events += len(items)
            except Exception as e:
                print(f"❌ 写入 JSON 失败 {json_path}: {e}")
                
    print(f"🎉 备份同步完成：新增了 {new_files} 个文件，更新并保存了 {success_files} 个 JSON 文件，同步了 {updated_events} 个事件数据！")

if __name__ == "__main__":
    main()
