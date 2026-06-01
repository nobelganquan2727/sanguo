# 大模型应用开发学习计划 — 基于三国志知识图谱 QA Agent

> 基于现有 `qa_agent.py` Text-to-Cypher 流水线，逐步升级为生产级 Agent 系统。

---

## 阶段1：鲁棒性 + Prompt 工程

**目标**：让系统从"能跑"变成"稳定可用"

### 1.1 Cypher 自修正循环（Error Recovery）
- 当 `run_query` 抛出异常时，捕获错误信息
- 将错误信息 + 原 Cypher 回传给 LLM，要求修正
- 设置最多 2 次重试，仍失败则优雅降级
- **核心技能**：LLM 作为调试器、重试策略、优雅降级

### 1.2 Prompt 模板化
- 将 Cypher 生成 Prompt 抽到独立文件或类中
- 引入 Few-shot 示例选择：根据用户问题动态选取最相关的 2-3 个查询示例
- **核心技能**：Prompt 模板化、Few-shot Learning、示例选择策略

### 1.3 结构化输出
- 使用 JSON Mode 或 Prompt 约束，让 LLM 返回 `{"cypher": "...", "reasoning": "..."}`
- 用 Pydantic 校验输出格式
- **核心技能**：Structured Output、Pydantic 校验、输出解析

### 1.4 基础安全过滤
- 对用户输入做简单的 Cypher 注入检测
- 限制查询结果数量，防止全表扫描拖垮数据库
- **核心技能**：安全边界意识、输入校验

---

## 阶段2：Agent 化改造

**目标**：从固定流水线升级为能自主决策的 Agent

### 2.1 引入 ReAct 决策循环
- 定义 Tools：`query_graph(cypher)`、`answer_directly()`、`ask_clarification()`
- LLM 先判断用户意图，再决定调用哪个工具
- **核心技能**：Tool Use / Function Calling、Agent 决策逻辑

### 2.2 多轮对话与记忆
- 引入 `ConversationBufferMemory` 或自管理 `messages`
- 支持上下文追问，如"那他后来呢？"
- **核心技能**：Memory 管理、上下文压缩、Message History

### 2.3 多工具扩展
- `search_events_by_keyword(keyword)`：全文检索事件描述
- `get_person_timeline(name)`：查询人物生平时间线
- `compare_two_persons(p1, p2)`：对比两位人物交集
- Agent 自主决定调用哪个工具及调用顺序
- **核心技能**：多工具编排、工具描述设计

### 2.4 计划型查询（Multi-step）
- 复杂问题拆分为多步：先查 A 再查 B，最后综合
- 例如"曹操和刘备在赤壁之战前有过哪些交集？"
- **核心技能**：多步推理、子目标分解

---

## 阶段3：RAG 混合检索 + 向量语义

**目标**：超越图谱精确匹配，支持模糊语义查询

### 3.1 事件文本向量化
- 对 `Event.description` 和 `source_text` 生成 Embedding
- 存入向量索引（ChromaDB / pgvector / Neo4j 自带向量索引）
- **核心技能**：Embedding 模型使用、向量存储

### 3.2 GraphRAG 混合检索
- 用户问题先做语义检索，找到相关事件
- 再根据事件 ID 精确查询图谱关联
- **核心技能**：Hybrid RAG、语义 + 结构化结合

### 3.3 查询路由（Query Routing）
- 判断问题类型：精确事实查询走图谱，模糊描述走向量
- **核心技能**：智能路由、分类器设计

---

## 阶段4：生产化与部署

**目标**：将 Agent 部署为可用服务

### 4.1 FastAPI 服务化
- 用 FastAPI 包装为 REST API
- 支持 SSE 流式输出回答
- **核心技能**：异步架构、流式生成、API 设计

### 4.2 可观测性
- 接入 LangSmith 或自研追踪，记录每次 LLM 调用的 Prompt / 输出 / 延迟
- 记录 Cypher 生成成功率、查询耗时
- **核心技能**：LLM Observability、性能分析

### 4.3 缓存与成本优化
- 相同/相似问题的 Cypher 和答案缓存
- 评估是否可用更小模型（如 deepseek-chat 降级为 deepseek-reasoner 或本地模型）处理简单任务
- **核心技能**：缓存策略、模型选型、成本控制

---

## 学习路线速览

```
阶段1: 鲁棒性 + Prompt 模板化
   |
   v
阶段2: Agent 化 + 多轮对话 + 多工具
   |
   v
阶段3: 向量检索 + GraphRAG 混合查询
   |
   v
阶段4: FastAPI 服务化 + 监控 + 部署
```

---

## 当前项目现状与下一步

**现有能力**：
- Text-to-Cypher 流水线（2 步：生成 Cypher -> 总结回答）
- Neo4j 图数据库连接
- 基于 LangChain ChatOpenAI 的 LLM 调用

**当前最大短板**：
- Cypher 写错直接崩溃，无容错
- Prompt 硬编码，难以迭代优化
- 无多轮对话能力
- 无 Agent 自主决策

**建议下一步**：先做 **1.1 Cypher 自修正循环**，改动最小、收益最大。
