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
        
    # 查询所有事件和他们被修改后的属性
    cypher = """
    MATCH (e:Event)
    OPTIONAL MATCH (e)-[:HAPPENED_AT]->(l:Location)
    RETURN e.protagonist AS protagonist, e.seq_index AS seq_index, 
           e.title AS title, e.description AS description, 
           e.std_start_year AS std_start_year, collect(l.name) AS locations
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
    success_files = 0
    updated_events = 0
    
    for protagonist, items in grouped_records.items():
        json_path = raw_dir / f"{protagonist}_events.json"
        if not json_path.exists():
            print(f"⚠️ [Skip] 找不到对应的原始 JSON 文件: {json_path}")
            continue
            
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                events = json.load(f)
        except Exception as e:
            print(f"❌ 读取 JSON 失败 {json_path}: {e}")
            continue
            
        file_updated = False
        for item in items:
            seq_index = item["seq_index"]
            if seq_index is None or seq_index < 0 or seq_index >= len(events):
                continue
                
            e = events[seq_index]
            
            # 检查是否有更新，并同步回 JSON 的对应字段
            # 地点
            locs_str = ",".join(sorted(filter(None, item["locations"])))
            # 原本的地点表示
            orig_locs = e.get("地点", "")
            # 对比并更新
            if orig_locs != locs_str:
                e["地点"] = locs_str
                file_updated = True
                
            # 年份
            year = item["std_start_year"]
            if e.get("std_start_year") != year:
                e["std_start_year"] = year
                file_updated = True
                
            # 简介
            desc = item["description"]
            if e.get("事件简介") != desc:
                e["事件简介"] = desc
                file_updated = True
                
            # 标题
            title = item["title"]
            if e.get("事件标题") != title:
                e["事件标题"] = title
                file_updated = True
                
            if file_updated:
                updated_events += 1
                
        if file_updated:
            try:
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(events, f, ensure_ascii=False, indent=2)
                success_files += 1
            except Exception as e:
                print(f"❌ 写入 JSON 失败 {json_path}: {e}")
                
    print(f"🎉 备份同步完成：更新了 {success_files} 个 JSON 文件，共同步 {updated_events} 个事件修正！")

if __name__ == "__main__":
    main()
