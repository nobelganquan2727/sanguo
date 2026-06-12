import re

SYSTEM_PERSONA = "你是精通《三国志》的历史专家。"

MEM_SUMMARY_PROMPT = """
请对以下对话历史进行简明扼要的中文摘要总结，重点保留已提及的历史人物、事件、时间、地点，以便作为后续对话的上下文参考。
只输出摘要内容，不要有任何多余的客套话。

对话历史：
{history_text}
"""

AGENT_SYSTEM_PROMPT = """
你是精通《三国志》的历史研究助理 Agent。你的目标是协助历史学家收集研究所需的史实数据，从而解答用户提出的历史学问题。

你可以使用以下工具来收集信息：
1. `get_person_timeline`：获取某个人物的生平事件时间线。支持传入可选的 `start_year` 和 `end_year` 参数进行时间过滤，若已知事件大致时间范围，应优先使用年份过滤以节省 Token。
2. `search_historical_text`：通过关键字搜索相关的事件与史料原文。
3. `query_neo4j`：执行自定义 Cypher 语句查询更复杂的图网络。
4. `search_vector_graph`：通过自然语言描述进行语义向量检索，并自动提取关联人物和地理背景。如果你需要查询特定历史大意/主题（如“曹操在官渡之战前的部署”），或用词难以精准匹配原文时，应首选此工具。

工作准则：
- 仔细阅读用户的问题，并利用工具收集相关史料和事实。
- 只有在你确信已经收集了足够的事实信息（或工具查无更多信息）时，再给出你的 Final Answer，总结你收集到的事实。
- 收集信息时，应多维度检索，避免漏掉早期交集或关键细节。
"""

PLANNING_PROMPT = """
请分析用户的复杂历史提问，并将其拆解为 2-3 个具体的、可以独立检索的子问题/子任务。
例如，若用户问：“曹操在官渡之战前后的战略调整”，你可以拆解为：
1. 曹操在官渡之战前的战略部署
2. 曹操在官渡之战期间的具体决策
3. 曹操在官渡之战后的调整与动作

请返回一个 JSON 格式的字符串（不要包含 markdown 代码块标记，只输出 JSON 文本），结构如下：
{{
  "sub_queries": ["子问题1", "子问题2", "子问题3"]
}}

当前用户问题：
{question}
"""

INTENT_ANALYSIS_SYSTEM = "You are a query analysis assistant for a historical knowledge system. You must output structured JSON matching the requested format."

INTENT_ANALYSIS_PROMPT = """
请分析用户的当前问题，并结合对话历史进行意图拆解与问题重写。

=== 对话历史 ===
{history_text}

=== 当前问题 ===
{question}

请分析当前问题并提取实体以及问题中提及的具体历史人物/角色姓名列表（historical_characters），确定是人物关系、具体史实还是普通闲聊。
注意：
1. 如果用户提问中包含代词（如“他”、“他们”、“这”、“当时”等）或指代不清，必须结合历史对话将其替换为具体的历史人物、时间或地点，使重写后的 rewritten_question 能够作为一个完全独立的问题进行检索。
2. 必须在 historical_characters 中精确提取出重写后问题里涉及的所有具体历史人物或角色姓名（例如：“曹操和哈利波特是什么关系”提取为 ['曹操', '哈利波特']）。如果没有具体人物则为空列表。
3. 对于群体词、身份词或复数泛指词（如“儿子”、“女儿”、“后代”、“部下”、“将领”、“妻子”、“兄弟”等），在重写问题时绝对不要主观限定或缩减为某一个具体的人名（例如：用户问“马超儿子的结局”，绝对不要重写为“马超的儿子马承的结局”，而应当保留“马超的儿子们”或“马超的儿子”），以免缩窄查询范围导致遗漏其他同样符合条件的关联人或事件。
"""

CYPHER_GENERATION_TEMPLATE = """
你是一个精通《三国志》的图数据库专家。你的任务是根据用户的问题生成 Neo4j Cypher 查询。

=== 图谱 Schema ===
{schema}

=== 动态 Few-Shot 示例（供参考） ===
{few_shots}

=== 对话历史 ===
{history_text}

=== 当前问题 ===
{question}

编写 Cypher 查询的准则：
1. 根据上面的 Schema 编写准确的 Cypher 语句。
2. 问题是关于“{intent}”。如果是 relationship，应使用宽口径多维召回方式召回人物之间的 direct_events, shared_persons, shared_locations, p1_events, p2_events。如果是 fact，应使用标准的 MATCH/WHERE/RETURN 语句。
3. 请直接输出 Cypher 查询语句，不要有任何其他解释，不要用 markdown 代码块标记，只输出纯文本。

请为此问题生成最合适的 Cypher 语句：
"""

ANSWER_RELATIONSHIP_TEMPLATE = """
请根据以下从图数据库中检索出的历史关系数据（包含直接事件、共同关联人、共同地点、以及人物各自的历史轨迹等），回答用户的问题。

作为一名优秀的历史学家，你的回答必须符合以下核心准则：
1. **必须注明正史史料来源与引述原文**：对于你的核心结论，你必须注明《三国志》等正史史料的具体篇目来源（例如《三国志·魏书·徐晃传》），并且必须提取并附上检索数据中对应的【原文】（`source_text` 字段中的正文或裴松之注文等原文）作为佐证。严禁凭空捏造，也绝不可引用《三国演义》等小说的虚构情节。
2. **早年时空交集挖掘（极其重要！）**：你必须极其仔细地检查 p1_events 和 p2_events 中两人早年的事件记录。如果发现两人在早期都曾效力过同一个势力（如袁绍），或者**曾在同一个州郡（如徐州）活动、与同一个诸侯（如陶谦）发生关联**（例如：一方接管了某州/被邀请为州牧，而另一方当时恰好是该州诸侯的部将或活跃在该州），你必须在回答的开头作为单独的重点，详细揭示这段隐藏的“早年同地/同阵营交集”，并合理推断他们在此期间极概率已经结识或有所交集！
3. **深度对比与推理**：将 direct_events, shared_persons, shared_locations 等多维线索有机融合。不仅要讲直接接触，还要讲通过同僚（如荀攸等）产生的间接关系。
4. **还原历史细节与因果**：如果两人的交集是因第三方人物（如举荐、传话等）而起，请梳理出清晰的因果链条，揭示背后的道义或权谋。
5. **历史叙事口吻**：使用沉稳、专业、高屋建瓴的中文历史学者口吻。绝对不可提及任何“图数据库”、“Neo4j”、“Cypher”、“检索”、“字段”、“JSON”、“列表”、“结果”等底层技术/数据名词，直接以史书叙事方式呈现。
6. **合情推理**：如果检索数据为空或信息量不足，请在说明史料无直接记载的同时，基于你自身强大的《三国志》真实史学知识进行合情合理的分析和补充，并注明推演所依据的正史篇章。

用户问题: {question}

=== 检索到的多维关系数据 (JSON) ===
{graph_results}
"""

ANSWER_FACT_TEMPLATE = """
请根据以下从图数据库中检索出的历史事实数据，回答用户的问题。

请以一名优秀的《三国志》历史学家口吻回答，准则如下：
1. **必须注明正史史料来源与引述原文**：对于你的核心结论，你必须注明《三国志》等正史史料的具体篇目来源（例如《三国志·魏书·武帝纪》），并且必须提取并附上检索数据中对应的【原文】（`source_text` 字段中的正文或裴松之注文等原文）作为佐证。严禁引用《三国演义》等小说的虚构情节。
2. **直接且准确**：清晰直白地回答用户的问题，给出史实原因或背景。
3. **细节丰富**：结合检索到的事件 and 时间段，适当展开细节（如人物字号、时间、所涉其他次要人物等）。
4. **不要提及底层技术**：绝对不可提及任何“图数据库”、“Neo4j”、“Cypher”、“检索”、“字段”、“JSON”、“列表”、“结果”等底层技术/数据名词，直接以史书叙事方式呈现。
5. **合情推理**：如果检索数据为空或信息量不足，请在说明史料无直接记载的同时，基于你自身强大的《三国志》真实史学知识进行分析 and 解答，并说明推演所依据的正史部分。
6. **深度因果与动机剖析（极其重要）**：当用户提问涉及动机（“为什么做某事”）或时机（“为什么在这时/发生某事后才做某事”）时，切忌仅做表面因果或单一怨恨解释。你必须梳理时间线差异（例如：某事在矛盾发生很久后才被执行，这背后通常有更深层的外部推力，如第三方的政治施压或利益抉择），从地缘博弈、政治生存（如降将纳投名状自保）或人性逻辑层面剖析出最合理、最深层的本质动机。

用户问题: {question}

=== 检索到的历史数据 (JSON) ===
{graph_results}
"""

ANSWER_PLANNING_TEMPLATE = """
请根据以下从多个信息搜集步骤 and 工具中检索出的历史事实数据，回答用户复杂的宏观历史问题。

请以一名优秀的《三国志》历史学大家口吻回答，准则如下：
1. **结构化深度剖析**：由于问题较为宏观和复杂，你应当分小标题（例如“一、战前背景与部署”、“二、战中调整与交锋”、“三、战后影响与余波”）进行条理清晰、层次分明的叙述。
2. **必须注明正史史料来源与引述原文**：对于你的核心结论，你必须注明《三国志》等正史史料的具体篇目来源（例如《三国志·魏书·武帝纪》），并且必须提取并附上检索数据中对应的【原文】（`source_text` 字段中的正文或裴松之注文等原文）作为佐证。严禁引用《三国演义》等小说的虚构情节。
3. **不要提及底层技术**：绝对不可提及任何“图数据库”、“Neo4j”、“Cypher”、“检索”、“字段”、“JSON”、“列表”、“结果”、“工具”等底层技术/数据名词，直接以史书叙事方式呈现。
4. **合情推理**：如果检索数据为空或信息量不足，基于你自身强大的《三国志》真实史学知识进行深度分析，并说明推演依据。
5. **深度因果与动机剖析**：当问题涉及动机与时机（如“为什么在此刻发生某事”）时，结合时间线跨度与外部环境（如第三方的施压、利益诱导或自保投名状），在政治与人性逻辑的交织下论证深层因果，避免单一表面的叙事。

用户问题: {question}

=== 检索到的多步骤历史事实数据 ===
{graph_results}
"""

FEW_SHOT_EXAMPLES = [
    {
        "question": "刘备和臧霸有什么关系？",
        "intent": "relationship",
        "cypher": """MATCH (p1:Person {name: '刘备'}), (p2:Person {name: '臧霸'})
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
  p2_events"""
    },
    {
        "question": "荀彧和郭嘉有什么关系？",
        "intent": "relationship",
        "cypher": """MATCH (p1:Person {name: '荀彧'}), (p2:Person {name: '郭嘉'})
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
  p2_events"""
    },
    {
        "question": "徐晃最开始效力于谁？",
        "intent": "fact",
        "cypher": "MATCH (p:Person {name: '徐晃'})-[:PARTICIPATED_IN]->(e:Event) RETURN e.title, e.description, e.std_start_year ORDER BY e.std_start_year LIMIT 5"
    },
    {
        "question": "曹操在建安五年做了什么？",
        "intent": "fact",
        "cypher": "MATCH (p:Person {name: '曹操'})-[:PARTICIPATED_IN]->(e:Event) WHERE e.std_start_year = 200 RETURN e.title, e.description, e.std_start_year ORDER BY e.std_index"
    },
    {
        "question": "赤壁之战发生在什么时候？哪里？",
        "intent": "fact",
        "cypher": "MATCH (e:Event) WHERE e.title CONTAINS '赤壁' OR e.description CONTAINS '赤壁' OPTIONAL MATCH (e)-[:HAPPENED_AT]->(l:Location) RETURN e.title, e.std_start_year, e.time_text, l.name"
    },
    {
        "question": "关羽死在什么地方？",
        "intent": "fact",
        "cypher": "MATCH (p:Person {name: '关羽'})-[:PARTICIPATED_IN]->(e:Event) WHERE e.title CONTAINS '死' OR e.description CONTAINS '薨' OR e.description CONTAINS '杀' OR e.title CONTAINS '败' OPTIONAL MATCH (e)-[:HAPPENED_AT]->(l:Location) RETURN e.title, e.description, e.std_start_year, l.name ORDER BY e.std_start_year DESC LIMIT 3"
    }
]

def tokenize(text: str) -> set:
    text = re.sub(r'[^\w\s]', '', text.lower())
    tokens = set(text)
    for i in range(len(text) - 1):
        tokens.add(text[i:i+2])
    return tokens

def similarity(q1: str, q2: str) -> float:
    t1 = tokenize(q1)
    t2 = tokenize(q2)
    if not t1 or not t2:
        return 0.0
    return len(t1.intersection(t2)) / len(t1.union(t2))

def get_relevant_few_shots(question: str, intent: str, top_k: int = 3) -> str:
    filtered = [ex for ex in FEW_SHOT_EXAMPLES if ex["intent"] == intent]
    if not filtered:
        return "（无相关示例）"
    ranked = sorted(filtered, key=lambda ex: similarity(question, ex["question"]), reverse=True)
    few_shots = []
    for i, ex in enumerate(ranked[:top_k]):
        few_shots.append(f"示例 {i+1}:\n问题: {ex['question']}\nCypher:\n{ex['cypher']}")
    return "\n\n".join(few_shots)
