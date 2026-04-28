import json
import hashlib
import re
import glob
import os
from neo4j import GraphDatabase

def generate_id(text: str) -> str:
    """用MD5为事件生成唯一图谱节点ID"""
    return hashlib.md5(text.encode('utf-8')).hexdigest()[:8]

def clean_locations_fallback(loc_str: str):
    """Fallback：简单按照标点分割"""
    if not loc_str or "不详" in loc_str:
        return []
    parts = re.split(r'[、/，,]', loc_str)
    return [p.strip() for p in parts if p.strip()]

def load_geo_dictionary():
    try:
        with open("data/sanguo_geo_dictionary.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print("⚠️ 警告: 未找到地名消歧字典。")
        return {}

def pipeline_to_cypher(json_file_path, geo_dict):
    print(f"--- 🚀 正在抽象数据文件: {json_file_path} ---")
    protagonist = os.path.basename(json_file_path).replace("_events.json", "")
    with open(json_file_path, 'r', encoding='utf-8') as f:
        events = json.load(f)

    cypher_queries = []
    
    for index, e in enumerate(events):
        event_caption = e.get('事件简介', str(e))
        event_id = f"evt_{generate_id(event_caption)}"
        
        # 提取时间与清洗后的标准化时间字段
        time_desc = e.get('时间', '')
        std_start_year = e.get('std_start_year')
        std_end_year = e.get('std_end_year')
        std_start_year_str = str(std_start_year) if std_start_year is not None else "null"
        std_end_year_str = str(std_end_year) if std_end_year is not None else "null"
        
        event_type = e.get('事件类型', '')
        event_title = e.get('事件标题', '').replace('\\', '\\\\').replace("'", r"\'") 
        original_text = e.get('原文', '').replace('\\', '\\\\').replace("'", r"\'")
        event_desc = e.get('事件简介', '').replace('\\', '\\\\').replace("'", r"\'")
        
        # 1. 创建 Event 核心节点，新增 seq_index 代表原始史料的叙述顺序，并打上主传记的烙印
        cypher_queries.append(
            f"MERGE (e:Event {{id: '{event_id}'}}) "
            f"SET e.type='{event_type}', e.time_text='{time_desc}', "
            f"e.std_start_year={std_start_year_str}, e.std_end_year={std_end_year_str}, "
            f"e.seq_index={index}, e.protagonist='{protagonist}', "
            f"e.title='{event_title}', e.source_text='{original_text}', e.description='{event_desc}';"
        )
        
        # 2. 地理空间解析打点：优先接管字典！！！
        raw_loc_str = e.get('地点', '')
        resolved_entities = geo_dict.get(raw_loc_str)
        
        if resolved_entities:
            for entity in resolved_entities:
                std_name = entity.get('std_name', '')
                region = entity.get('region', '')
                lat = entity.get('lat')
                lng = entity.get('lng')
                
                lat_str = str(lat) if lat is not None else "null"
                lng_str = str(lng) if lng is not None else "null"
                
                # 创建带有【汉末州郡层级】与【现代坐标】的精细定点 Node！
                cypher_queries.append(
                    f"MERGE (l:Location {{name: '{std_name}'}}) "
                    f"SET l.region='{region}', l.lat={lat_str}, l.lng={lng_str};"
                )
                cypher_queries.append(f"MATCH (e:Event {{id: '{event_id}'}}), (l:Location {{name: '{std_name}'}}) MERGE (e)-[:HAPPENED_AT]->(l);")
        else:
            # 降级处理 (字典中没有对应的隐射时)
            fallback_locs = clean_locations_fallback(raw_loc_str)
            for loc in fallback_locs:
                cypher_queries.append(f"MERGE (l:Location {{name: '{loc}'}});")
                cypher_queries.append(f"MATCH (e:Event {{id: '{event_id}'}}), (l:Location {{name: '{loc}'}}) MERGE (e)-[:HAPPENED_AT]->(l);")
                
        # 3. 人物实体提取与关联
        characters = e.get('相关人物', [])
        for ch in characters:
            cypher_queries.append(f"MERGE (p:Person {{name: '{ch}'}});")
            cypher_queries.append(f"MATCH (p:Person {{name: '{ch}'}}), (e:Event {{id: '{event_id}'}}) MERGE (p)-[:PARTICIPATED_IN]->(e);")
            
    return cypher_queries

if __name__ == "__main__":
    geo_dict = load_geo_dictionary()
    print(f"✅ 成功加载全局地名词典，包含 {len(geo_dict)} 条映射规则。")
    
    # 之前是测试，现在我们要真正的万佛朝宗，把 300 多个文件全部挂进去！
    all_json_files = glob.glob("data/raw/*_events.json")
    all_queries = []
    
    # 第一步！清空全表以迎接全新的数据维度
    all_queries.append("MATCH (n) DETACH DELETE n;")
    
    for f in all_json_files:
        all_queries.extend(pipeline_to_cypher(f, geo_dict))
        
    print(f"\n--- ✅ 成功生成全量知识图谱 Cypher 语句 ({len(all_queries)} 条) ---")
    print("准备将数据灌入本地 Neo4j 数据库...")
    
    pwd = "12345678"
    try:
        driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", pwd))
        driver.verify_connectivity()
        print("✅ 成功连接到 Neo4j 数据库！正在写入庞大的历史关联网络，请耐心等待...")
        
        with driver.session() as session:
            for q in all_queries:
                session.run(q)
                
        print(f"🎉 成功导入全部 {len(all_queries)} 条知识节点与关系网！数据地基竣工！")
        print("现在可以去浏览器 http://localhost:7474 里面冲浪了！")
        driver.close()
    except Exception as e:
        print(f"❌ 数据库连接或写入失败: {e}")
