import json
import os
from neo4j import GraphDatabase

# 内置核心三国的种子地缘、世族与亲缘元数据（历史学术对齐）
# 即使不联网或没有运行大模型抽取，运行此脚本也能立刻一键注入最关键的人物社交圈！
SEED_METADATA = [
    {
        "name": "曹操",
        "hometown": "沛国谯县",
        "clan": "谯国曹氏",
        "relations": [
            {"to": "曹仁", "type": "从弟", "relation_type": "KINSHIP"},
            {"to": "曹洪", "type": "从弟", "relation_type": "KINSHIP"},
            {"to": "曹丕", "type": "长子", "relation_type": "KINSHIP"},
            {"to": "曹植", "type": "子", "relation_type": "KINSHIP"},
            {"to": "夏侯惇", "type": "族弟/大将", "relation_type": "KINSHIP"},
            {"to": "夏侯渊", "type": "族弟/大将", "relation_type": "KINSHIP"},
            {"to": "袁绍", "type": "宿敌/对手", "relation_type": "ENEMY"},
            {"to": "刘备", "type": "对手/青梅煮酒", "relation_type": "ENEMY"}
        ]
    },
    {
        "name": "荀彧",
        "hometown": "颍川颍阴",
        "clan": "颍川荀氏",
        "relations": [
            {"to": "荀攸", "type": "从子(侄子)", "relation_type": "KINSHIP"},
            {"to": "曹操", "type": "主臣/军师", "relation_type": "RULER_SUBJECT"},
            {"to": "郭嘉", "type": "引荐/同乡", "relation_type": "RECOMMENDED"},
            {"to": "钟繇", "type": "好友/同乡", "relation_type": "ALLY"},
            {"to": "陈群", "type": "通家/同乡", "relation_type": "ALLY"}
        ]
    },
    {
        "name": "荀攸",
        "hometown": "颍川颍阴",
        "clan": "颍川荀氏",
        "relations": [
            {"to": "荀彧", "type": "族叔", "relation_type": "KINSHIP"},
            {"to": "曹操", "type": "主臣/谋主", "relation_type": "RULER_SUBJECT"}
        ]
    },
    {
        "name": "陈群",
        "hometown": "颍川许昌",
        "clan": "颍川陈氏",
        "relations": [
            {"to": "曹操", "type": "主臣/九品官人法", "relation_type": "RULER_SUBJECT"},
            {"to": "曹丕", "type": "挚友/托孤重臣", "relation_type": "ALLY"},
            {"to": "荀彧", "type": "敬重/同乡", "relation_type": "ALLY"}
        ]
    },
    {
        "name": "郭嘉",
        "hometown": "颍川阳翟",
        "clan": "颍川郭氏",
        "relations": [
            {"to": "曹操", "type": "主臣/祭酒", "relation_type": "RULER_SUBJECT"},
            {"to": "荀彧", "type": "举主(被推荐)", "relation_type": "RULER_SUBJECT"}
        ]
    },
    {
        "name": "刘备",
        "hometown": "幽州涿郡",
        "clan": "涿郡刘氏",
        "relations": [
            {"to": "关羽", "type": "结拜兄弟/御侮", "relation_type": "ALLY"},
            {"to": "张飞", "type": "结拜兄弟/御侮", "relation_type": "ALLY"},
            {"to": "诸葛亮", "type": "三顾茅庐/君臣契合", "relation_type": "RULER_SUBJECT"},
            {"to": "赵云", "type": "大将/心腹", "relation_type": "ALLY"},
            {"to": "刘禅", "type": "长子", "relation_type": "KINSHIP"},
            {"to": "孙权", "type": "政治联姻/同盟", "relation_type": "ALLY"},
            {"to": "刘表", "type": "同宗/客居", "relation_type": "ALLY"}
        ]
    },
    {
        "name": "诸葛亮",
        "hometown": "徐州琅邪",
        "clan": "琅邪诸葛氏",
        "relations": [
            {"to": "诸葛瑾", "type": "胞兄(仕吴)", "relation_type": "KINSHIP"},
            {"to": "诸葛均", "type": "胞弟", "relation_type": "KINSHIP"},
            {"to": "诸葛瞻", "type": "长子", "relation_type": "KINSHIP"},
            {"to": "刘备", "type": "主臣/托孤", "relation_type": "RULER_SUBJECT"},
            {"to": "刘禅", "type": "辅政/相父", "relation_type": "RULER_SUBJECT"},
            {"to": "庞统", "type": "凤雏/同僚", "relation_type": "ALLY"},
            {"to": "马良", "type": "挚友/白眉", "relation_type": "ALLY"},
            {"to": "马谡", "type": "器重/参军", "relation_type": "ALLY"},
            {"to": "司马懿", "type": "生前对手/北伐抗衡", "relation_type": "ENEMY"}
        ]
    },
    {
        "name": "孙权",
        "hometown": "吴郡富春",
        "clan": "吴郡孙氏",
        "relations": [
            {"to": "孙坚", "type": "父亲", "relation_type": "KINSHIP"},
            {"to": "孙策", "type": "长兄/开国基石", "relation_type": "KINSHIP"},
            {"to": "周瑜", "type": "托孤辅政/大都督", "relation_type": "RULER_SUBJECT"},
            {"to": "鲁肃", "type": "挚友/单刀赴会", "relation_type": "RULER_SUBJECT"},
            {"to": "陆逊", "type": "社稷之臣/女婿", "relation_type": "RULER_SUBJECT"},
            {"to": "张昭", "type": "辅吴重臣/张公", "relation_type": "RULER_SUBJECT"}
        ]
    },
    {
        "name": "周瑜",
        "hometown": "庐江舒县",
        "clan": "庐江周氏",
        "relations": [
            {"to": "孙策", "type": "总角之交/断金同盟", "relation_type": "ALLY"},
            {"to": "孙权", "type": "辅佐/主臣", "relation_type": "RULER_SUBJECT"},
            {"to": "鲁肃", "type": "挚友/指囷相赠", "relation_type": "ALLY"}
        ]
    },
    {
        "name": "鲁肃",
        "hometown": "临淮东城",
        "clan": "临淮鲁氏",
        "relations": [
            {"to": "孙权", "type": "主臣/榻上策", "relation_type": "RULER_SUBJECT"},
            {"to": "周瑜", "type": "好友", "relation_type": "ALLY"},
            {"to": "诸葛亮", "type": "促成孙刘联盟", "relation_type": "ALLY"}
        ]
    },
    {
        "name": "陆逊",
        "hometown": "吴郡吴县",
        "clan": "吴郡陆氏",
        "relations": [
            {"to": "孙权", "type": "主臣/抗魏先锋", "relation_type": "RULER_SUBJECT"},
            {"to": "陆抗", "type": "子/吴国名将", "relation_type": "KINSHIP"},
            {"to": "顾雍", "type": "同僚/江东大族", "relation_type": "ALLY"}
        ]
    },
    {
        "name": "司马懿",
        "hometown": "河内温县",
        "clan": "河内司马氏",
        "relations": [
            {"to": "司马师", "type": "长子", "relation_type": "KINSHIP"},
            {"to": "司马昭", "type": "次子", "relation_type": "KINSHIP"},
            {"to": "曹操", "type": "主臣/心存忌惮", "relation_type": "RULER_SUBJECT"},
            {"to": "曹丕", "type": "挚友/勋戚同盟", "relation_type": "ALLY"}
        ]
    }
]

def load_static_metadata(file_path="data/character_static_metadata.json"):
    """
    优先读取本地生成的外部 JSON 文件，若不存在则保存并使用内置种子数据。
    """
    if os.path.exists(file_path):
        print(f"📂 发现外部静态元数据文件: {file_path}，正在载入...")
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        print(f"💡 未找到 {file_path}，已为您自动创建并保存精排内置种子元数据。")
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(SEED_METADATA, f, ensure_ascii=False, indent=2)
        return SEED_METADATA

def import_static():
    metadata = load_static_metadata()
    cypher_queries = []

    # 1. 预先建立好地缘类型和家族节点的约束/索引（提升合并速度）
    # 注：社区版不支持同一事务中混用模式定义和数据合并，因此全部采用标准 MERGE 语法保证兼容性

    for char in metadata:
        name = char.get("name")
        hometown = char.get("hometown")
        clan = char.get("clan")

        # 匹配/构建当前人物节点 (安全合并，保留之前事件已生成的人物)
        cypher_queries.append(f"MERGE (p:Person {{name: '{name}'}});")

        # 关联地缘节点 (籍贯)
        if hometown:
            cypher_queries.append(f"MERGE (l:Location {{name: '{hometown}'}}) SET l.type = '地缘郡县';")
            cypher_queries.append(
                f"MATCH (p:Person {{name: '{name}'}}), (l:Location {{name: '{hometown}'}}) "
                f"MERGE (p)-[:HOMETOWN]->(l);"
            )

        # 关联士族家族节点 (Clan)
        if clan:
            cypher_queries.append(f"MERGE (c:Clan {{name: '{clan}'}});")
            cypher_queries.append(
                f"MATCH (p:Person {{name: '{name}'}}), (c:Clan {{name: '{clan}'}}) "
                f"MERGE (p)-[:MEMBER_OF]->(c);"
            )

        # 关联与其他人物的静态社交圈关系 (血缘、引荐、宿敌等)
        for rel in char.get("relations", []):
            to_person = rel.get("to")
            rel_type = rel.get("relation_type", "RELATED_TO")
            desc = rel.get("type", "")

            # 匹配/创建关系目标人物
            cypher_queries.append(f"MERGE (p2:Person {{name: '{to_person}'}});")
            # 建立强类型关系边
            cypher_queries.append(
                f"MATCH (p1:Person {{name: '{name}'}}), (p2:Person {{name: '{to_person}'}}) "
                f"MERGE (p1)-[r:{rel_type}]->(p2) "
                f"SET r.desc = '{desc}';"
            )

    print(f"⚡ 成功生成 {len(cypher_queries)} 条增量导入 Cypher 语句。")
    
    # 连接本地数据库进行万佛朝宗
    pwd = "12345678"
    db_uri = "bolt://localhost:7687"
    print(f"🚀 正在连接 Neo4j 数据库 ({db_uri})...")
    
    try:
        driver = GraphDatabase.driver(db_uri, auth=("neo4j", pwd))
        driver.verify_connectivity()
        
        with driver.session() as session:
            # 开启显式事务以极大加速批量写入
            with session.begin_transaction() as tx:
                for q in cypher_queries:
                    tx.run(q)
            
        print("🎉 静态地缘、士族、世系关系已完美增量注入！您的三国志关系图谱已彻底升维！")
        driver.close()
    except Exception as e:
        print(f"❌ 导入数据库时发生异常: {e}")

if __name__ == "__main__":
    import_static()
