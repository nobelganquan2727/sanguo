"""
图谱 Schema 定义
供 LLM 参考
"""

COMPACT_GRAPH_SCHEMA = """
你正在操作一个三国志历史知识图谱（Neo4j），图谱结构如下：

【节点类型】
- Person    { name: string, alias: string, faction: string, description: string }
- Event     { id: string, title: string, description: string, source_text: string, time_text: string, translation: string, std_start_year: integer, seq_index: integer, chapter: string }
- Location  { name: string, level: string, type: string, region: string, modern: string, lat: float, lng: float }
- Group     { id: string, name: string, description: string, origin: string, ancestral_home: string, surname: string, representatives: list[string] }
- MajorEvent { id: string, title: string, description: string, year: integer, location_name: string, location_region: string, location_desc: string, characters: list[string] }

【关系类型】
- (Person)-[:PARTICIPATED_IN]->(Event)
- (Person)-[:PARTICIPATED_IN]->(MajorEvent)
- (Person)-[:REPRESENTATIVE_OF]->(Group)
- (Event)-[:HAPPENED_AT]->(Location)
- (Event)-[:INVOLVES_GROUP]->(Group)
- (Event)-[:BELONGS_TO_MAJOR]->(MajorEvent)
- (MajorEvent)-[:HAPPENED_AT]->(Location)
- (Location)-[:BELONGS_TO]->(Location)
"""
