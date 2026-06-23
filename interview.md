# 《三国志数字沙盘》LLM 智能体系统与 LLM 应用开发深度面试指南

本项目是一个将**关系型数据库 (MySQL)**、**图数据库 (Neo4j)** 和**大语言模型 (DeepSeek/DashScope)** 深度融合的 RAG 智能体系统。以下是围绕本项目核心架构与代码实现提炼出的 10 大 LLM 应用开发高频面试/技术深探问题，重点结合了项目中的实际代码。

---

## 目录
1. [Q1: 为什么在历史人物/关系检索场景中选择 Graph RAG 而非传统 Vector RAG？](#q1-为什么在历史人物关系检索场景中选择-graph-rag-而非传统-vector-rag)
2. [Q2: 如何解决大模型生成 Cypher 语句时的语法错误与幻觉？（自愈设计）](#q2-如何解决大模型生成-cypher-语句时的语法错误与幻觉自愈设计)
3. [Q3: 面对海量图数据召回，如何进行 Token 防防与防止 Context Window 溢出？](#q3-面对海量图数据召回如何进行-token-防御与防止-context-window-溢出)
4. [Q4: 如何设计严密的防幻觉（Anti-Hallucination）与查无拒答（No-Data Fallback）机制？](#q4-如何设计严密的防幻觉anti-hallucination与查无拒答no-data-fallback机制)
5. [Q5: 面对复杂的宏观历史问题，如何设计 Agent 的规划、拆解与流式思考链路？](#q5-面对复杂的宏观历史问题如何设计-agent-的规划拆解与流式思考链路)
6. [Q6: 如何实现语义缓存（Semantic Cache）来降低大模型成本和响应延迟？](#q6-如何实现语义缓存semantic-cache来降低大模型成本和响应延迟)
7. [Q7: 本项目是如何设计与实现多步推理（Multi-Step Reasoning）的？（ReAct 与 Plan-and-Solve）](#q7-本项目是如何设计与实现多步推理multi-step-reasoning的react-与-plan-and-solve)
8. [Q8: 本项目作为一个复杂的 RAG/智能体系统，是如何协同并整合多个异构信息源与存储介质的？](#q8-本项目作为一个复杂的-rag智能体系统是如何协同并整合多个异构信息源与存储介质的)
9. [Q9: 在 Python 编写的 LLM Agent 中，如何处理同步阻断并设计高并发 of 异步生成器输出？](#q9-在-python-编写的-llm-agent-中如何处理同步阻断并设计高并发的异步生成器输出)
10. [Q10: 如何优雅地将短期会话记忆（Chat Session Memory）从无状态客户端传递重构为基于 Redis 的缓存设计？](#q10-如何优雅地将短期会话记忆chat-session-memory从无状态客户端传递重构为基于-redis-的缓存设计)
11. [Q11: 如何评估一个复杂的 RAG/智能体系统？本项目是如何实现类似 RAGAS 的自动化评估指标的？](#q11-如何评估一个复杂的-rag智能体系统本项目是如何实现类似-ragas-的自动化评估指标的)

---



### Q1: 为什么在历史人物/关系检索场景中选择 Graph RAG 而非传统 Vector RAG？

#### 面试官视角
评估候选人对数据拓扑结构的理解，是否能跳出“万物皆可嵌入（Vector Embedding）”的思维定势，讲清图拓扑与向量检索在多跳关系召回上的本质差异。

#### 本项目实践
传统的 Vector RAG 适合查找**孤立的语义片段**，但在检索“刘备和臧霸有什么关系？”时，向量检索只会匹配到同时出现这两个名字的碎片，极容易漏掉通过**中间人（如吕布、曹操）**或**相同事件/地点**产生的隐性关联。

本项目通过 [schema.py](file:///Users/kansen/Documents/Code/Sanguozhi/agent/schema.py) 建立实体与关系的显式建模：
*   节点：`Person`, `Event`, `Location`, `Group`, `MajorEvent`
*   关系：`PARTICIPATED_IN` (人参与事件), `HAPPENED_AT` (事件发生于地点), `REPRESENTATIVE_OF` (人属于利益集团) 等。

当询问关系时，项目在 [prompts.py](file:///Users/kansen/Documents/Code/Sanguozhi/agent/prompts.py#L199-L233) 中通过 Cypher Few-Shot 引导 LLM 召回多维度拓扑信息（直接交集、共同关联人、共同地点、人物各自轨迹）：
```cypher
MATCH (p1:Person {name: '刘备'}), (p2:Person {name: '臧霸'})
RETURN
  [(p1)-[:PARTICIPATED_IN]->(e:Event)<-[:PARTICIPATED_IN]-(p2) | {title: e.title}] AS direct_events,
  [(p1)-[:PARTICIPATED_IN]->(e_s1:Event)<-[:PARTICIPATED_IN]-(p3:Person)-[:PARTICIPATED_IN]->(e_s2:Event)<-[:PARTICIPATED_IN]-(p2) | p3.name][..15] AS shared_persons,
  [(p1)-[:PARTICIPATED_IN]->(el1:Event)-[:HAPPENED_AT]->(l:Location)<-[:HAPPENED_AT]-(el2:Event)<-[:PARTICIPATED_IN]-(p2) | l.name][..15] AS shared_locations
```
这种**宽口径多维召回**（Wide-Interval Multi-Dimensional Recall）能够确保多跳关系链（Multi-hop relations）的完整，再由 LLM 进行语义提炼，实现比 Vector RAG 更深刻的“时空交集挖掘”（比如两人曾在同盟或同一地点共事）。

---

### Q2: 如何解决大模型生成 Cypher 语句时的语法错误与幻觉？（自愈设计）

#### 面试官视角
Text-to-SQL 或 Text-to-Cypher 经常因为实体无法对齐或语法越界而报错，考察候选人是否具备 LLM 闭环容错与自修复（Self-Correction/Self-Healing）设计经验。

#### 本项目实践
本项目采用了**三层防线**确保 Cypher 的生成与执行率：

1.  **前置意图拆解与指代消解**：在 [qa_agent.py:L342-391](file:///Users/kansen/Documents/Code/Sanguozhi/agent/qa_agent.py#L342-L391) 的 `analyze_intent` 中，利用大模型将用户提问结合历史对话上下文进行重写（消解代词如“他”、“当时”），提取出明确的实体与关系类别，避免 LLM 在生成 Cypher 时由于上下文代词造成语义漂移。
2.  **Schema 注入与 Few-shot 约束**：生成 Cypher 时强行注入 [schema.py](file:///Users/kansen/Documents/Code/Sanguozhi/agent/schema.py) 中的图谱定义，并给出 `FEW_SHOT_EXAMPLES`。
3.  **Cypher 语法自愈（Self-Healing Loop）**：在 [tools.py:L121-169](file:///Users/kansen/Documents/Code/Sanguozhi/agent/tools.py#L121-L169) 的 `query_neo4j_async` 工具中，设计了最大 2 次的重试修正回路。当 Neo4j 执行报错时，将**报错日志**与**错误 Cypher** 重新喂给大模型进行自修正：
    ```python
    while retry_count <= max_retries:
        if retry_count > 0:
            correction_prompt = f"上一次生成的 Cypher 报错了。\n【错误】：{last_error}\n【Cypher】：{current_cypher}\n请仔细对照 Schema 修正错误，只输出纯 Cypher 文本。"
            execution_messages.append(AIMessage(content=current_cypher))
            execution_messages.append(HumanMessage(content=correction_prompt))
            res = await llm_complex.ainvoke(execution_messages)
            current_cypher = res.content.strip()
        try:
            results = await run_query_async(current_cypher)
            return truncate_tool_output(json.dumps(results, ensure_ascii=False))
        except Exception as e:
            last_error = str(e)
            retry_count += 1
    ```
    通过这种机制，代码实现了对 LLM 生成 Cypher 的动态约束和运行时修复。

---

### Q3: 面对海量图数据召回，如何进行 Token 防御与防止 Context Window 溢出？

#### 面试官视角
大人物（如曹操、刘备）在图数据库中的关系节点可能成千上万，如果无脑 dump 会导致上下文窗口爆炸、响应变慢甚至账单暴增。考察候选人在工程落地上对 Token 消费的防御性设计。

#### 本项目实践
本项目采用了**静态防溢约束**、**防御性数据截断**与**对话记忆提炼**相结合的治理方案：

1.  **工具级别的 Prompt 引导与参数约束**：在 [tools.py:L172-173](file:///Users/kansen/Documents/Code/Sanguozhi/agent/tools.py#L172-L173) 的 `get_person_timeline_async` Docstring 中，明确警告大模型：“*曹操、刘备等大人物的事件极多，查询时必须传入 `start_year` 和 `end_year` 过滤到具体的时间段...*”，通过工具描述限制大模型的越界召回。
2.  **Defensive Truncation Utility（防御性截断）**：在 [tools.py:L52-113](file:///Users/kansen/Documents/Code/Sanguozhi/agent/tools.py#L52-L113) 中设计了 `truncate_tool_output` 函数。若召回结果字符长度超过 12,000，该工具不会直接抛弃数据，而是解析 JSON 数组，安全剥离多余条目并阶段大文本字段（如限制 `source_text` 最大 500 字），同时自动附带 `【卷宗纪要说明】` 告知 Agent：“因内容过多已截断，仅展示前 N 条，若想深入请缩窄查询范围”。这避免了 JSON 损坏，也引导了 Agent 的下一步决策。
3.  **多轮对话记忆压缩**：在 [qa_agent.py:L301-340](file:///Users/kansen/Documents/Code/Sanguozhi/agent/qa_agent.py#L301-L340) 中，若多轮会话轮数超过 6 轮，自动使用低成本大模型将老旧历史消息（除去最近 4 轮）提炼成一段紧凑的摘要，在节约 Token 的同时保持会话的长期连贯性。

---

### Q4: 如何设计严密的防幻觉（Anti-Hallucination）与查无拒答（No-Data Fallback）机制？

#### 面试官视角
大模型具有天然的幻觉倾向，容易信口雌黄（比如将《三国演义》虚构桥段说成正史，或编造历史上不存在的人物）。如何通过数据源（Grounding）与规则校验强行阻断幻觉？

#### 本项目实践
本项目在 Agent Pipeline 中强制执行了**两道关卡**：

1.  **实体前置存在性校验（Characters Check）**：
    在 [qa_agent.py:L218-238](file:///Users/kansen/Documents/Code/Sanguozhi/agent/qa_agent.py#L218-L238) 中，`check_characters_exist` 在进入检索逻辑前，先提取问题涉及的所有历史人名，在 Neo4j 中执行预查验证是否存在此人物节点。如传入“哈利波特”等正史无载人名，则在 [qa_agent.py:L421-429](file:///Users/kansen/Documents/Code/Sanguozhi/agent/qa_agent.py#L421-L429) 中直接硬编码返回：“*抱歉，正史《三国志》中并未记载有关该人物的信息，老夫无从考证*”，直接阻断 LLM 的瞎编可能。
2.  **空数据精准兜底拒答（Grounding Validation）**：
    传统的 Agent 在工具返回空数据时，会根据自身预训练知识直接回答，导致幻觉生成。本项目在 [qa_agent.py:L60-80](file:///Users/kansen/Documents/Code/Sanguozhi/agent/qa_agent.py#L60-L80) 通过 `has_valid_db_records` 函数检测工具的 Observations。如果所有工具调用返回的都是空数组、空串、未找到或报错，则在 [qa_agent.py:L477-484](file:///Users/kansen/Documents/Code/Sanguozhi/agent/qa_agent.py#L477-L484) 中立刻切断生成，直接答复：“*抱歉，在正史《三国志》及相关史料库中未搜寻到任何与该问题相关的史实记录...*”。这确保了“**无正史数据则坚决不答**”的学术严谨性。

---

### Q5: 面对复杂的宏观历史问题，如何设计 Agent 的规划、拆解与流式思考链路？

#### 面试官视角
对于像“分析曹操在官渡之战前后的战略调整”这类高度复杂的宏观问题，单次 Tool Call 或单次 Prompt 生成往往只能得到肤浅或片面的答案。考察候选人对 Agentic Planning (Plan-and-Solve) 的理解以及对前端高响应度的 SSE (流式传输) 架构设计。

#### 本项目实践

1.  **意图检测与任务规划（Task Planning）**：
    如果提问被分类为 `complex_planning`，Agent 不会直接进入查询，而是首先调用 `PLANNING_PROMPT` 将宏观问题拆解成 2-3 个独立的子任务。
    例如，“曹操在官渡之战前后的战略调整”被拆解为：
    *   子问题 1: 曹操在官渡之战前的战略部署
    *   子问题 2: 曹操在官渡之战期间的具体决策
    *   子问题 3: 曹操在官渡之战后的调整与动作
    然后，Agent 通过循环在 `run_agent_loop` 中依次处理每个子任务，逐个调用最合适的工具召回事实，最后通过 `ANSWER_PLANNING_TEMPLATE` 结构化组装（分小标题叙述）输出最终答案。
2.  **SSE 异步流式输出与思考轨迹展示**：
    由于 Agent 的规划与多次检索非常耗时，为了避免前端等待卡死，后端 [server.py:L289-295](file:///Users/kansen/Documents/Code/Sanguozhi/server.py#L289-L295) 返回 `StreamingResponse`：
    ```python
    @app.post("/api/ask")
    async def api_ask(req: AskRequest):
        return StreamingResponse(
            ask_question_stream(req.question, req.history),
            media_type="text/event-stream"
        )
    ```
    在 [qa_agent.py:L197-300](file:///Users/kansen/Documents/Code/Sanguozhi/agent/qa_agent.py#L197-L300) 中，`QAStreamPipeline` 配合 `asyncio.Queue` 管道，将幕僚的内部状态和思考过程作为 `"status"` 事件（如“🤖 [幕僚] 决定翻检对应史书，调用工具...”），将 LLM 生成的回复作为 `"text"` 实时抛出。前端捕获后，可以在界面左侧以“思考轨迹”的日志流形式呈现，大幅提升了交互体验与系统透明度。

---

### Q6: 如何实现语义缓存（Semantic Cache）来降低大模型成本和响应延迟？

#### 面试官视角
LLM 的响应时间通常在数秒甚至数十秒，API 调用费用高昂。当用户重复或高度相似地提问时，如何利用向量检索构建“语义层面的缓存（Semantic Cache）”进行毫秒级响应？

#### 本项目实践
本项目在 [agent/cache.py](file:///Users/kansen/Documents/Code/Sanguozhi/agent/cache.py) 中通过 **ChromaDB (向量数据库) + DashScope text-embedding-v2** 实现了轻量级的语义缓存机制：

1.  **缓存架构设计**：
    *   使用 ChromaDB 作为本地向量存储（开发环境使用 `EphemeralClient` 方便隔离，生产环境使用 `PersistentClient` 持久化到 `logs/chroma_cache`）。
    *   以 `cosine_similarity`（余弦相似度）度量新问题与已缓存问题的距离。
2.  **语义缓存查询逻辑**：
    在 `lookup_cache` 中，为当前问题生成 Embedding，在 Chroma 集合中进行 top-k 查询。如果最相似问题的相似度 $1 - distance \ge 0.92$ (默认阈值)，则代表意义高度一致（如“曹操是谁”与“阿瞒是谁”），直接取出对应的元数据 `answer` 返回，绕过大模型推理。
    ```python
    distance = results["distances"][0][0]
    similarity = 1.0 - distance
    if similarity >= threshold:
        return answer, similarity
    ```
3.  **防御性缓存写入（Defensive Save）**：
    在 `save_cache` 中，程序在写入缓存前会主动过滤掉临时系统错误或由于“翻阅不便”而做出的兜底错误回答：
    ```python
    if not answer or answer.startswith("Error") or "病体抱恙" in answer or "简牍翻阅多有不便" in answer:
        return
    ```
    这确保了写入缓存的数据全部都是高质量、考证成功的正面历史回答，防止垃圾数据污染缓存库。

---

### Q7: 本项目是如何设计与实现多步推理（Multi-Step Reasoning）的？（ReAct 与 Plan-and-Solve）

#### 面试官视角
复杂的知识库问答或链式探查中，大模型很难通过单次 Prompt 拍脑门给出精准答案。考察候选人对 Agent 循环迭代推理（ReAct Loop）和多级子课题任务编排（Plan-and-Solve）的实际工程落地经验。

#### 本项目实践
本项目在 [qa_agent.py](file:///Users/kansen/Documents/Code/Sanguozhi/agent/qa_agent.py) 中通过**双层嵌套的多步推理架构**来应对复杂提问：

1.  **微观多步推理：闭环 ReAct 迭代**：
    在 [qa_agent.py:L240-299](file:///Users/kansen/Documents/Code/Sanguozhi/agent/qa_agent.py#L240-L299) 的 `run_agent_loop` 方法中，Agent 会进行最大 5 步的推理-执行循环（ReAct Loop）。模型通过 LLM 判断当前信息是否完备，并决策调用对应的史书翻检工具（如 `query_neo4j_async`, `get_person_timeline_async` 等）。工具返回的数据以 `ToolMessage` 身份实时作为下一轮推理的 Observation 背景喂回模型：
    ```python
    while step < max_steps:
        response = await llm_with_tools.ainvoke(agent_messages)
        agent_messages.append(response)
        
        # 决策收敛，跳出循环
        if not response.tool_calls:
            break
            
        # 串行/并行执行工具，追加 ToolMessage 到上下文
        for tool_call in response.tool_calls:
            obs_str = await execute_tool(tool_call)
            agent_messages.append(ToolMessage(content=obs_str, tool_call_id=tool_id))
        step += 1
    ```
2.  **宏观多步推理：Plan-and-Solve 课题拆解**：
    在 [qa_agent.py:L441-470](file:///Users/kansen/Documents/Code/Sanguozhi/agent/qa_agent.py#L441-L470) 中，如果意图分析判定提问属于宏观复杂规划类，系统会调用 `PLANNING_PROMPT` 先将大任务拆解为数个具体的、可以独立检索的子课题（Sub-queries）。接着，系统循环调度 `run_agent_loop` 对这些子课题串行做步步探查，最后汇总并使用结构化模板渲染输出。

这种**微观 ReAct 决策 + 宏观 Sub-task 规划**的结合，使智能体能够循序渐进地探查复杂的历史线索，确保结论有据可查。

---

### Q8: 本项目作为一个复杂的 RAG/智能体系统，是如何协同并整合多个异构信息源与存储介质的？

#### 面试官视角
实际的企业级 LLM 应用很少只有单点存储（比如只用一个向量库），往往是关系数据库、图数据库、本地静态配置和向量缓存的混合架构。考察候选人对于多数据源协同架构（Multi-source Heterogeneous Architecture）与一致性写入的设计经验。

#### 本项目实践
本项目没有将所有数据一股脑塞进 Neo4j，而是根据**读写频率、数据拓扑和业务属性**，有机整合了 **4 个不同类型的信息源**：

1.  **Neo4j（图拓扑与向量混合主库）**：
    *   **作用**：维护《三国志》的网状关联（人物、传记事件、地理行政区划）和 1024 维 BGE-M3 向量。
    *   **检索方式**：通过 Cypher 和 Neo4j Vector Index 混合 RAG。
2.  **MySQL（关系型数据库 - 异步反馈与审核流）**：
    *   **作用**：用于存储用户提交的纠错反馈（Feedback）并管理审批状态，避免频繁对 Neo4j 执行低效写入。
    *   **双写协同**：在 [server.py:L220-288](file:///Users/kansen/Documents/Code/Sanguozhi/server.py#L220-L288) 的 `apply_admin_feedback` 中，管理员审核通过后，系统会启动跨库双写逻辑：先向 Neo4j 写入 Cypher 变更，再将 MySQL 的反馈记录状态设为 `approved`。
3.  **ChromaDB（本地向量库 - 语义缓存层）**：
    *   **作用**：独立存储用户历史问答 Embedding，作为语义缓存层拦截重复/相似 query，减少对 DeepSeek 接口的消耗。
    *   **代码体现**：[agent/cache.py](file:///Users/kansen/Documents/Code/Sanguozhi/agent/cache.py)。
4.  **本地静态 JSON 配置文件（地理辐射与归档数据）**：
    *   **作用**：用于行政建制边界的递归展开。例如，在 [server.py:L104-140](file:///Users/kansen/Documents/Code/Sanguozhi/server.py#L104-L140) 的 `expand_location_names` 中，用户在地图上点击大省份，后端从本地 `eastern_han_admin.json` 中递归展开所有县城和别名列表，然后再传给 Neo4j 匹配，用较小的本地 CPU 换取了昂贵的图数据库递归开销。

---

### Q9: 在 Python 编写的 LLM Agent 中，如何处理同步阻断并设计高并发的异步生成器输出？

#### 面试官视角
大模型 Agent 开发中常遇到的“硬伤”是：大模型请求、同步数据库驱动（如传统的 MySQL/Neo4j 阻断库）、本地文件 I/O 都是同步阻塞的，这在 FastAPI 这种基于单线程事件循环（Event Loop）的框架里会导致整个服务卡死。考察候选人对异步编程（`asyncio`）、线程池 Offloading 与异步生成器（Async Generator）模式的深度驾驭能力。

#### 本项目实践
本项目从三个维度化解了同步阻断风险，实现了平滑的异步流式输出：

1.  **异步化改造与线程池桥接（Thread Offloading）**：
    当驱动或第三方包只支持同步 API 时，使用 `loop.run_in_executor` 将阻塞调用转交给后台 ThreadPool 运行。例如在 [tools.py:L115-117](file:///Users/kansen/Documents/Code/Sanguozhi/agent/tools.py#L115-L117) 和 [L285-291](file:///Users/kansen/Documents/Code/Sanguozhi/agent/tools.py#L285-L291) 中：
    ```python
    async def run_query_async(cypher: str, params: dict = None) -> list[dict]:
        loop = asyncio.get_running_loop()
        # 丢进默认线程池执行同步 Neo4j 查询，Await 让出事件循环控制权
        return await loop.run_in_executor(None, run_query, cypher, params)
    ```
2.  **生产者-消费者协程编排（Asyncio Queue + Background Task）**：
    在 [qa_agent.py:L569-596](file:///Users/kansen/Documents/Code/Sanguozhi/agent/qa_agent.py#L569-L596) 的流式问答函数中，为了实现前端 SSE (Server-Sent Events) 打字机效果，将大模型执行的复杂检索（包含多次 Tool Call 推理）用 `asyncio.create_task` 包装为**后台非阻塞任务**，通过 `asyncio.Queue` 管道与主协程（消费者）通信：
    ```python
    # 1. 启动后台推理任务 (不阻塞主线程)
    producer_task = asyncio.create_task(producer())
    
    # 2. 消费者以异步生成器方式实时 yield 队列中的元素给 FastAPI
    while True:
        event = await queue.get()
        if event is None:
            break
        yield json.dumps(event)
    ```
3.  **FastAPI `StreamingResponse` 异步串联**：
    *   后端 [server.py](file:///Users/kansen/Documents/Code/Sanguozhi/server.py#L289-L295) 的接口声明为 `async def`，并返回 `StreamingResponse` 吞吐异步生成器，确保每一个长连接只占用最少的系统资源，提升了高并发场景下的吞吐率。

---

### Q10: 如何优雅地将短期会话记忆（Chat Session Memory）从无状态客户端传递重构为基于 Redis 的缓存设计？

#### 面试官视角
无状态 API 迫使前端在每次对话时都传送全量 `history` 数组，这在长对话中消耗大量网络带宽。考量候选人如何利用 **Redis 缓存** 实现有状态会话管理（Stateful Session Management），并重点考察在生产环境下的“降级容灾设计（Fallback Strategy）”。

#### 本项目实践
本项目在 [server.py](file:///Users/kansen/Documents/Code/Sanguozhi/server.py) 中通过引入异步 Redis 客户端与 SSE 拦截技术，实现了解耦与缓存持久化：

1.  **全局连接池与启动健康检查（Connection Pooling & Startup Healthcheck）**：
    为了避免每次 API 请求都重复经历 Redis 客户端实例化与 `PING` 握手的 TCP 开销，我们在 [server.py](file:///Users/kansen/Documents/Code/Sanguozhi/server.py) 中将 `redis_client` 声明为全局单例连接池。同时，利用 FastAPI 的 `startup` 事件，仅在服务器启动时进行一次 `PING` 连通性测试：
    ```python
    redis_client = aioredis.from_url(redis_url, encoding="utf-8", decode_responses=True)
    redis_available = False

    @app.on_event("startup")
    async def check_redis_connectivity():
        global redis_available
        try:
            await redis_client.ping()
            redis_available = True
        except Exception:
            redis_available = False
    ```
    如果在启动时或运行中连接中断，系统会自动回退使用客户端自带的 `history` 数组，确保服务高可用。
2.  **异步会话调阅**：
    若传入 `session_id` 且 `redis_available` 为真，使用全局客户端的 `LRANGE` 取回历史消息列表。由于配置了 `decode_responses=True`，读取到的字符串无需手动解码：
    ```python
    raw_msgs = await redis_client.lrange(req.session_id, 0, -1)
    history = [json.loads(m) for m in raw_msgs]
    ```
3.  **SSE 串流拦截与双写回写**：
    由于采用了流式生成，无法在一开始就拿到完整回答。后端设计了 `sse_generator` 包装协程，在 `yield` 返回流式块的同时累计字符。在流式生成安全收尾且未发生系统故障或兜底拒答的前提下，通过 `RPUSH` 跨线程将用户输入和完整 AI 回答追加存入 Redis 列表，并强制为该 Session 设置 1 小时过期时间（`EXPIRE`）防止内存无限膨胀：
    ```python
    # 异步生成器循环
    async for chunk in ask_question_stream(req.question, history):
        yield chunk
        accumulate_text(chunk)
    
    # 成功生成后归档写入 Redis
    if use_redis:
        await redis_client.rpush(req.session_id, user_msg)
        await redis_client.rpush(req.session_id, ai_msg)
        await redis_client.expire(req.session_id, 3600)
    ```

---

### Q11: 如何评估一个复杂的 RAG/智能体系统？本项目是如何实现类似 RAGAS 的自动化评估指标的？

#### 面试官视角
评估 RAG 与智能体（Agent）系统的性能是落地生产环境的核心难点。传统的端到端评测只能由人工或大模型对最终回答打分，**无法定位瓶颈究竟在检索端（Retrieval）还是生成端（Generation）**。
考察候选人是否理解 **Ragas (Retrieval Augmented Generation Assessment)** 的核心理念，以及是否能脱离外部黑盒库，在工程中**独立设计并实现一套低成本、全闭环的 LLM-as-a-Judge 自动化评测指标体系**。

#### 本项目实践
本项目在 [tests/evaluate_ragas.py](file:///Users/kansen/Documents/Code/Sanguozhi/tests/evaluate_ragas.py) 中实现了一套类似 Ragas 的自动化自动化评测系统。整个架构由**中间状态拦截器**、**大模型裁判组**与**指标计算层**组成。

##### 1. RAGAS 评估的四维矩阵
我们定义了四个核心评估指标，分别针对检索和生成两个阶段进行量化打分（0-10分）：

| 评估阶段 | 评估指标 | 评估方向 | 核心逻辑 |
| :--- | :--- | :--- | :--- |
| **生成端 (Generation)** | **忠实度 (Faithfulness)** | 回答 vs 检索上下文 | 检查生成的回答中宣称的每一句史实，是否都能在检索出的数据中找到依据。若脱离上下文“脑补”或捏造，则扣分（防幻觉）。如果上下文为空而回答包含大量史实，打分为 0。 |
| **生成端 (Generation)** | **答案相关性 (Relevance)** | 回答 vs 用户问题 | 评估回答是否正面、直接、不啰嗦地响应了用户问题。若出现异常拒答、答非所问或废话连篇，则扣分。 |
| **检索端 (Retrieval)** | **检索召回率 (Context Recall)** | 检索上下文 vs 参考概念 | 检查我们预设的黄金标准实体/概念列表（Ground Truth），有多少比例被检索工具成功拉取出来，衡量检索完整度。 |
| **检索端 (Retrieval)** | **检索精准度 (Context Precision)** | 检索上下文 vs 用户问题 | 评估检索出的工具上下文信息密度。如果拉取了大量无关的冗余噪声，说明精准度低，导致上下文窗口被垃圾数据污染。 |

---

##### 2. 核心代码实现：无侵入式中间状态捕获与队列消耗
为了在不修改 Agent 业务代码的前提下获取中间状态，我们在 `evaluate_ragas.py` 中直接构造 `QAStreamPipeline` 并以异步方式消耗其生成的事件流，从而在执行完毕后直接提取出**最终生成的 Answer** 和**工具检索到的全部上下文 (Observations)**：

```python
# 1. 构造 RAG 流式管道
queue = asyncio.Queue()
pipeline = QAStreamPipeline(question, history=[], queue=queue, handler=None)

start_time = time.time()
try:
    # 2. 异步拉起后台推理任务
    pipeline_task = asyncio.create_task(pipeline.execute_pipeline())
    
    # 3. 实时消耗队列，驱动 Agent 运行并保持非阻塞
    while not pipeline_task.done() or not queue.empty():
        try:
            event = await asyncio.wait_for(queue.get(), timeout=0.05)
        except asyncio.TimeoutError:
            if pipeline_task.done() and queue.empty():
                break
    
    await pipeline_task
    answer = "".join(pipeline.collected_text)
except Exception as e:
    answer = f"Error: {e}"
    pipeline.all_observations = []

# 4. 从 pipeline 提取所有工具调用的原始检索观测数据 (Context)
context_str = "\n\n".join([
    f"【工具: {obs['tool']} | 参数: {obs['query']}】\n数据: {obs['result']}"
    for obs in pipeline.all_observations
])
```

---

##### 3. LLM-as-a-Judge 的 Prompt 级设计（单次调用降本增效）
传统的 Ragas 框架计算每个指标都需要调用一次大模型，15个测试样本需要 60 次 API 调用，成本和延迟极高。
我们设计了**单次调用裁判模板**（Single-Call Judge Prompt），将 4 项指标的打分和原因归并到一次 LLM 交互中，并强制输出标准的 JSON 格式：

```python
JUDGE_PROMPT_TEMPLATE = """
请针对以下给出的“用户问题”、“系统生成的回答”、“参考历史概念”以及“检索到的工具上下文”，在以下四个 RAG 评估维度进行专业、客观的打分（0-10分），并给出具体的评价原因：

【评估维度与评分标准】：
1. 忠实度 (faithfulness_score)：
   - 评估系统生成的“回答”是否完全忠实于“检索到的工具上下文”。如果上下文为空且回答中包含大量事实阐述（全靠预训练知识脑补），请评 0 分。
2. 答案相关性 (answer_relevance_score)：
   - 评估生成的“回答”是否正面、切题、完整地回应了“用户问题”。
3. 检索召回率 (context_recall_score)：
   - 评估“检索到的工具上下文”对“参考历史概念”的覆盖程度（已成功检索出的比例）。
4. 检索精准度 (context_precision_score)：
   - 评估“检索到的工具上下文”中与“用户问题”相关的有用信息占比，若充斥大量冗余噪声则扣分。

注意：如果检索上下文为空（说明是闲聊类型事件），请将 `faithfulness_score`、`context_recall_score` 和 `context_precision_score` 设为 -1，仅对 `answer_relevance_score` 进行评分。

【输入数据】：
用户问题：{question}
系统生成的回答：{answer}
参考历史概念/实体：{reference}
检索到的工具上下文：{context}

【输出格式】：
返回的 JSON 必须包含以下字段，并且可以直接被 json.loads 解析，请不要添加任何 markdown 代码包裹：
{{
  "faithfulness_score": 10.0,
  "faithfulness_reason": "评价原因...",
  "answer_relevance_score": 10.0,
  "answer_relevance_reason": "评价原因...",
  "context_recall_score": 10.0,
  "context_recall_reason": "评价原因...",
  "context_precision_score": 10.0,
  "context_precision_reason": "评价原因..."
}}
"""
```

---

##### 4. 典型评估基准数据与分析 (基准样本：15 题)
运行 `python3 tests/evaluate_ragas.py` 后，系统在 [ragas_report_latest.md](file:///Users/kansen/Documents/Code/Sanguozhi/logs/eval_reports/ragas_report_latest.md) 导出的自动化评估汇总结果如下：

| 评估维度 | 平均得分 (0-10) | 诊断分析 |
| :--- | :---: | :--- |
| **忠实度 (Faithfulness)** | **6.46** | 表现一般。LLM 极易在未成功检索到知识时，使用其 parametric memory（预训练知识）进行丰富作答，导致非忠实于 Context 的幻觉生成。 |
| **答案相关性 (Answer Relevance)** | **9.33** | 表现极佳。大模型对历史问题的意图拆解与总结能力非常强，即使没检索到数据也会用严谨的文风或兜底应答正面解题。 |
| **检索召回率 (Context Recall)** | **8.27** | 表现良好。图数据库节点拓扑和 Few-shot Cypher 保证了核心人物关系和时间线的高效召回。 |
| **检索精准度 (Context Precision)** | **6.85** | 表现偏低。召回的文本片段中混入了过多冗余噪声（如搜索关联人物时拉出了大量不相干的纪要原文），稀释了信息密度。 |
| **综合 RAG 得分 (Overall RAG)** | **7.73** | 系统整体可用度较好，核心优化方向为**过滤检索噪音（提升精准度）**与**强制约束非检索数据输出（提升忠实度）**。 |

---

##### 5. 真实案例剖析：利用 RAGAS 诊断系统瓶颈
以下是评测报告中一个典型的 **0分忠实度** 案例，完美展示了 RAGAS 在排查 RAG 缺陷时的核心价值：

*   **用户提问**: “刘备和孙权在赤壁之战前后的合作关系是怎样的？”
*   **参考概念 (Ground Truth)**: `同盟, 联姻, 借荆州, 南郡, 周瑜`
*   **评测得分**:
    *   `Answer Relevance`: `9.0 / 10`
    *   `Context Recall`: `8.0 / 10`
    *   `Context Precision`: `6.0 / 10`
    *   `Faithfulness`: **`0.0 / 10` (彻底不忠实/严重幻觉！)**

**【诊断过程】**：
1.  **检索层行为**：
    由于用户问题长且复杂，检索端发起了 `search_historical_text` 并传入关键词 `'赤壁之战 刘备 孙权 联盟'`。由于该超长关键词过于严苛，底层全文检索没有召回任何与之匹配的文档块，返回了空列表。
2.  **生成层行为**：
    虽然检索上下文基本上是空的（或充斥着长坂坡之战等无关噪音），但由于该提问不是简单的 Fact 类单实体问题，Agent 的 Intent-Checking 判定其为复杂规划（Complex Planning），绕过了针对“空 Observation”的前置 Grounding Fallback 兜底（只在所有 Fact 检索全空时直接拒绝）。
    结果，大模型（DeepSeek-Chat）凭借自身强大的三国知识库，生成了一篇结构极其漂亮、逻辑十分清晰的联盟分析（包含鲁肃诸葛亮游说、周瑜兵力分配、借荆州真相等）。
3.  **RAGAS 裁判判决**：
    大模型裁判在对比 `回答` 与 `检索到的工具上下文` 时，发现生成的回答长篇大论而且史实极多，但**检索上下文中全是空或噪音，没有一句话支持这些内容**。裁判给出了无情的 `0.0` 分：
    > *裁判评语*：“系统生成的回答包含了大量关于合作关系的详细史实描述（如鲁肃与诸葛亮的双簧、兵力对比等）。然而，检索到的工具上下文中并无这些内容。回答完全不忠实于检索到的上下文，存在明显的幻觉（以 RAG 真实度衡量）。”

**【改进方案】**：
这说明**系统不需要微调大模型或修改 Prompt，而是检索机制存在盲区**。
我们需要引入**查询重写/查询分词（Query Rewriting/Tokenization）**，把 `'赤壁之战 刘备 孙权 联盟'` 拆解为 `(赤壁之战 AND 刘备) OR (孙权 AND 借荆州)`，或者借助 Neo4j 图谱实体做多跳路径检索（Multi-hop retrieval），把实体检索结果成功召回（提升 Context Precision & Recall）。这样，大模型就可以在忠实于上下文的前提下生成同样的优质回答，使 Faithfulness 得分回升到 `10.0`。


