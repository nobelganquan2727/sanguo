"""
图谱 Schema 定义
供 LLM 生成 Cypher 时参考
"""

GRAPH_SCHEMA = """
你正在操作一个三国志历史知识图谱（Neo4j），图谱结构如下：

【节点类型】
- Person    {
    name: string,                             # 历史人物姓名
    alias: string,                            # 字（如：元叹，可能为空）
    faction: string,                          # 所属政治/军事势力（如：孙吴，可能为空）
    description: string                       # 人物简介（可能为空）
  }
- Event     {
    id: string,                               # 事件唯一编码（evt_开头的MD5截断）
    title: string,                            # 事件标题
    description: string,                      # 事件详细描述
    source_text: string,                      # 史料原文段落
    time_text: string,                        # 原文时间描述
    translation: string,                      # 现代白话翻译描述
    std_start_year: integer,                  # 标准化开始年份（公元，整数，可为null）
    seq_index: integer,                       # 事件在原传记中的先后顺序序号
    chapter: string                           # 事件所属史书卷名（如：三国志_卷十八）
  }
- Location  {
    name: string,                             # 地名
    level: string,                            # 地理行政层级（"State"(州), "Commandery"(郡), "County"(县), "Subcounty"(县以下/要塞/山川), "Unresolved"）
    type: string,                             # 建制具体类型（如 州、郡、县、关、国等）
    region: string,                           # 归属区域（如 扬州-吴郡）
    modern: string,                           # 现代地名对照
    lat: float,                               # 纬度坐标（可为null）
    lng: float                                # 经度坐标（可为null）
  }
- Group     {
    id: string,                               # 集团/世家唯一ID（如 ru_ying, wu_jun_gu）
    name: string,                             # 集团或世家大族名称（如 汝颍集团, 吴郡顾氏）
    description: string,                      # 集团/世家简介
    origin: string,                           # 地理源流/构成区域（如 豫州-汝南郡、颍川郡）
    ancestral_home: string,                   # 世家祖籍地（如 扬州-吴郡吴县）
    surname: string,                          # 世家姓氏（如 顾）
    representatives: list[string]             # 代表人物姓名列表
  }
- MajorEvent {
    id: string,                               # 重大事件ID（如 guan_du_zhi_zhan, wan_cheng_zhi_zhan）
    title: string,                            # 重大事件名称（如 官渡之战, 宛城之战）
    description: string,                      # 事件整体背景及进程描述
    year: integer,                            # 发生年份
    location_name: string,                    # 核心发生地点名称
    location_region: string,                  # 发生地点所属区域
    location_desc: string,                    # 地点描述说明
    characters: list[string]                  # 核心参与人物姓名列表
  }

【关系类型】
- (Person)-[:PARTICIPATED_IN]->(Event)         # 人物直接参与某段传记中的事件
- (Person)-[:PARTICIPATED_IN]->(MajorEvent)    # 人物直接参与了某场重大历史事件
- (Person)-[:REPRESENTATIVE_OF]->(Group)       # 人物是某政治集团/世家大族的代表人物
- (Event)-[:HAPPENED_AT]->(Location)           # 传记事件发生的地理位置
- (Event)-[:INVOLVES_GROUP]->(Group)           # 传记事件牵涉或涉及某政治集团/世家
- (Event)-[:BELONGS_TO_MAJOR]->(MajorEvent)    # 传记事件属于某个宏观重大历史事件
- (MajorEvent)-[:HAPPENED_AT]->(Location)      # 重大历史事件发生的地理位置
- (Location)-[:BELONGS_TO]->(Location)         # 地理位置间的行政建制隶属关系（如 县->郡->州）

【查询进阶技巧 - 多维关系/深度推理】
当你需要查询人物、集团或重大事件之间的关系时，可利用模式列表推导式或直接 MATCH 查询：
1. 两人共同参与的事件：MATCH (p1:Person {name: '关羽'})-[:PARTICIPATED_IN]->(e:Event)<-[:PARTICIPATED_IN]-(p2:Person {name: '曹操'})
2. 人物所属的利益集团：MATCH (p:Person {name: '顾雍'})-[:REPRESENTATIVE_OF]->(g:Group) RETURN g.name, g.description
3. 某个集团/世家参与的所有事件：MATCH (g:Group {name: '吴郡顾氏'})<-[:INVOLVES_GROUP]-(e:Event) RETURN e.title, e.std_start_year
4. 某场重大战争（如官渡之战）中的所有具体传记细节事件：MATCH (me:MajorEvent {title: '官渡之战'})<-[:BELONGS_TO_MAJOR]-(e:Event) RETURN e.title, e.description, e.time_text
5. 查询地理位置层级：MATCH (l1:Location {name: '吴县'})-[:BELONGS_TO]->(l2)-[:BELONGS_TO]->(l3) RETURN l1.name, l2.name, l3.name

【常用查询模式举例】
# 查两人多维关系与时空轨迹交集（包含人物的字、势力、集团等背景）
MATCH (p1:Person {name: '荀彧'}), (p2:Person {name: '郭嘉'})
OPTIONAL MATCH (p1)-[:PARTICIPATED_IN]->(e1:Event)
WITH p1, p2, e1 ORDER BY e1.std_start_year ASC
WITH p1, p2, collect({title: e1.title, description: e1.description, time: e1.time_text, year: e1.std_start_year})[..30] AS p1_events
OPTIONAL MATCH (p2)-[:PARTICIPATED_IN]->(e2:Event)
WITH p1, p2, p1_events, e2 ORDER BY e2.std_start_year ASC
WITH p1, p2, p1_events, collect({title: e2.title, description: e2.description, time: e2.time_text, year: e2.std_start_year})[..30] AS p2_events
RETURN
  [(p1)-[:PARTICIPATED_IN]->(e:Event)<-[:PARTICIPATED_IN]-(p2) | {title: e.title, description: e.description, year: e.std_start_year}] AS direct_events,
  [(p1)-[:REPRESENTATIVE_OF]->(g:Group)<-[:REPRESENTATIVE_OF]-(p2) | g.name] AS shared_groups,
  [(p1)-[:PARTICIPATED_IN]->(el1:Event)-[:HAPPENED_AT]->(l:Location)<-[:HAPPENED_AT]-(el2:Event)<-[:PARTICIPATED_IN]-(p2) | {location: l.name, p1_event: el1.title, p2_event: el2.title}][..15] AS shared_locations,
  p1_events,
  p2_events
"""
