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

【查询进阶技巧 - 多维关系/深度推理】
当你需要查询两个人物/实体之间的关系、交集或需要大模型进行历史推导时，强烈建议生成一个**宽口径多维召回**的 Cypher 语句。
利用模式列表推导式 (Pattern Comprehension) 召回以下多个维度的数据。这样能防止笛卡尔积爆炸，且能提供极佳的历史推理背景：
1. direct_events: 两人直接共同参与的事件
2. shared_persons: 共同关联的第三方人物 (如共同的主公、推荐人、同事) 及各自关联的事件
3. shared_locations: 共同去过的地点及各自在该地点发生的事件
4. p1_events: 人物1的重要生平事件 (限制10条)
5. p2_events: 人物2的重要生平事件 (限制10条)

【常用查询模式举例】
# 查两人共同参与的事件 (常规)
MATCH (p1:Person {name: '关羽'})-[:PARTICIPATED_IN]->(e:Event)<-[:PARTICIPATED_IN]-(p2:Person {name: '曹操'})
RETURN e.title, e.description, e.std_start_year ORDER BY e.std_start_year

# 查两人多维关系与时空轨迹交集 (极力推荐，按年份升序排序以对齐早年及生平完整轨迹)
MATCH (p1:Person {name: '荀彧'}), (p2:Person {name: '郭嘉'})
OPTIONAL MATCH (p1)-[:PARTICIPATED_IN]->(e1:Event)
WITH p1, p2, e1 ORDER BY e1.std_start_year ASC
WITH p1, p2, collect({title: e1.title, description: e1.description, time: e1.time_text, year: e1.std_start_year})[..30] AS p1_events
OPTIONAL MATCH (p2)-[:PARTICIPATED_IN]->(e2:Event)
WITH p1, p2, p1_events, e2 ORDER BY e2.std_start_year ASC
WITH p1, p2, p1_events, collect({title: e2.title, description: e2.description, time: e2.time_text, year: e2.std_start_year})[..30] AS p2_events
RETURN
  [(p1)-[:PARTICIPATED_IN]->(e:Event)<-[:PARTICIPATED_IN]-(p2) | {title: e.title, description: e.description, year: e.std_start_year}] AS direct_events,
  [(p1)-[:PARTICIPATED_IN]->(e_s1:Event)<-[:PARTICIPATED_IN]-(p3:Person)-[:PARTICIPATED_IN]->(e_s2:Event)<-[:PARTICIPATED_IN]-(p2) WHERE p3.name <> p1.name AND p3.name <> p2.name | {mediator: p3.name, p1_event: e_s1.title, p2_event: e_s2.title}][..15] AS shared_persons,
  [(p1)-[:PARTICIPATED_IN]->(el1:Event)-[:HAPPENED_AT]->(l:Location)<-[:HAPPENED_AT]-(el2:Event)<-[:PARTICIPATED_IN]-(p2) | {location: l.name, p1_event: el1.title, p2_event: el2.title}][..15] AS shared_locations,
  p1_events,
  p2_events

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
