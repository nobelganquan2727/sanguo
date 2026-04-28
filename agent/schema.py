"""
图谱 Schema 定义
供 LLM 生成 Cypher 时参考
"""

GRAPH_SCHEMA = """
你正在操作一个三国志历史知识图谱（Neo4j），图谱结构如下：

【节点类型】
- Person    {name: string}                              # 历史人物
- Event     {id, title, description, type,              # 历史事件
             source_text, time_text,
             std_start_year, std_end_year,              # 标准化年份（公元，整数，可为null）
             seq_index, protagonist}                    # 主传人物名
- Location  {name, region, lat, lng}                   # 地理位置

【关系类型】
- (Person)-[:PARTICIPATED_IN]->(Event)    # 人物参与事件
- (Event)-[:HAPPENED_AT]->(Location)     # 事件发生地点

【常用查询模式举例】
# 查两人共同参与的事件
MATCH (p1:Person {name: '关羽'})-[:PARTICIPATED_IN]->(e:Event)<-[:PARTICIPATED_IN]-(p2:Person {name: '曹操'})
RETURN e.title, e.description, e.std_start_year ORDER BY e.std_start_year

# 查某年发生的事件
MATCH (e:Event) WHERE e.std_start_year = 200
RETURN e.title, e.protagonist, e.description LIMIT 20

# 查某人的所有事件
MATCH (p:Person {name: '诸葛亮'})-[:PARTICIPATED_IN]->(e:Event)
RETURN e.title, e.std_start_year, e.type ORDER BY e.std_start_year

# 查某地发生的事件
MATCH (e:Event)-[:HAPPENED_AT]->(l:Location {name: '赤壁'})
RETURN e.title, e.protagonist, e.std_start_year

# 查与某人有关联的其他人
MATCH (p1:Person {name: '刘备'})-[:PARTICIPATED_IN]->(e:Event)<-[:PARTICIPATED_IN]-(p2:Person)
WHERE p2.name <> '刘备'
RETURN DISTINCT p2.name, count(e) as shared_events ORDER BY shared_events DESC LIMIT 10
"""
