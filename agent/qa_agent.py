import os
import sys
import json
import asyncio
from typing import List, AsyncGenerator, Callable, Awaitable

# 让脚本可以直接通过 python3 agent/qa_agent.py 运行
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from dotenv import load_dotenv
from agent.prompts import (
    SYSTEM_PERSONA,
    PLANNING_PROMPT,
    INTENT_ANALYSIS_SYSTEM,
    INTENT_ANALYSIS_PROMPT,
    ANSWER_TEMPLATE,
)
from agent.schema import GRAPH_SCHEMA
from agent.observability import active_callback_var
from agent.cache import lookup_cache, save_cache

from agent.utils import (
    has_valid_db_records,
    extract_events_from_observations,
    validate_dag_plan,
    resolve_args_placeholders,
    clean_obs_for_synthesis,
    consolidate_and_deduplicate_observations
)

from agent.schemas import (
    IntentAnalysis,
    TaskSpec,
    DAGPlan
)

load_dotenv()
from langfuse import Langfuse

from agent.tools import (
    get_llm,
    query_neo4j_async,
    get_person_timeline_async,
    search_historical_text_async,
    search_vector_graph_async,
    active_send_event_var,
    run_query_async,
    truncate_tool_output
)


class BaseSubAgent:
    def __init__(self, pipeline: 'QAStreamPipeline'):
        self.pipeline = pipeline

    async def send_event(self, event_type: str, content: str):
        await self.pipeline.send_event(event_type, content)


class IntentAnalyzerAgent(BaseSubAgent):
    async def analyze(self) -> IntentAnalysis:
        await self.send_event("status", "🧠 [意图分析] 正在递呈上意并消解前文代词...")
        analysis = None
        try:
            structured_llm = self.pipeline.llm_cheap.with_structured_output(IntentAnalysis, method="function_calling")
            analysis_messages = [
                SystemMessage(content=INTENT_ANALYSIS_SYSTEM),
                HumanMessage(content=INTENT_ANALYSIS_PROMPT.format(history_text=self.pipeline.history_text, question=self.pipeline.question))
            ]
            analysis = await structured_llm.ainvoke(analysis_messages)
        except Exception as e:
            await self.send_event("status", f"⚠️ [意图分析] structured_output 失败 ({str(e)})，尝试原生 JSON 兜底...")
            try:
                fallback_prompt = INTENT_ANALYSIS_PROMPT.format(history_text=self.pipeline.history_text, question=self.pipeline.question) + "\n请返回一个符合上述 JSON schema 的对象（确保不要用 markdown 代码块标记，只输出 JSON 文本）。"
                res_msg = await self.pipeline.llm_cheap.ainvoke([
                    SystemMessage(content=INTENT_ANALYSIS_SYSTEM + " You must output raw JSON only."),
                    HumanMessage(content=fallback_prompt)
                ])
                res = res_msg.content.strip()
                
                if res.startswith("```json"):
                    res = res[7:]
                elif res.startswith("```"):
                    res = res[3:]
                if res.endswith("```"):
                    res = res[:-3]
                res = res.strip()
                
                data = json.loads(res)
                analysis = IntentAnalysis(
                    type=data.get("type", "complex"),
                    rewritten_question=data.get("rewritten_question", self.pipeline.question),
                    entities=data.get("entities", []),
                    historical_characters=data.get("historical_characters", []),
                    clarify_message=data.get("clarify_message"),
                    clarify_options=data.get("clarify_options")
                )
            except Exception as e2:
                await self.send_event("status", f"⚠️ [意图分析] 兜底解析失败 ({str(e2)})，降级至经验规则分类。")
                q_type = "complex"
                if any(w in self.pipeline.question for w in ["刚才", "之前", "什么", "谁", "你好", "哈喽"]):
                    if "刚才" in self.pipeline.question or "之前" in self.pipeline.question or any(greet in self.pipeline.question for greet in ["你好", "哈喽"]):
                        q_type = "generic_chat"
                analysis = IntentAnalysis(
                    type=q_type,
                    rewritten_question=self.pipeline.question,
                    entities=[],
                    historical_characters=[]
                )
        return analysis

    async def handle_generic_chat(self):
        await self.send_event("status", "💬 [闲聊回答] 无需翻检古籍，正在直接答复...")
        system_content = f"{SYSTEM_PERSONA}请根据用户的当前问题和对话历史进行回答。"
        if self.pipeline.user_memory_block:
            system_content = self.pipeline.user_memory_block + "\n" + system_content
        chat_messages = [SystemMessage(content=system_content)]
        for role, content in self.pipeline.history_to_process:
            if role == "user":
                chat_messages.append(HumanMessage(content=content))
            else:
                chat_messages.append(AIMessage(content=content))
        chat_messages.append(HumanMessage(content=self.pipeline.question))
        
        async for chunk in self.pipeline.llm_cheap.astream(chat_messages):
            if chunk.content:
                self.pipeline.collected_text.append(chunk.content)
                await self.send_event("text", chunk.content)


class PlannerAgent(BaseSubAgent):
    async def plan(self, rewritten_q: str) -> DAGPlan:
        await self.send_event("status", "📋 [复杂规划] 正在启动 DeepSeek-R1 深度逻辑推理拆解...")
        
        # 1. 深度推理拆解规划建议
        llm_reasoner = get_llm("reasoner")
        planning_prompt_formatted = PLANNING_PROMPT.format(schema=GRAPH_SCHEMA, question=rewritten_q)
        
        messages = [
            SystemMessage(content="You are a planning assistant for a historical knowledge base. You must logically analyze the question, map it to the graph schema, and decide how to decompose it into steps."),
            HumanMessage(content=planning_prompt_formatted)
        ]
        
        reasoning_thought = ""
        try:
            res_reason = await llm_reasoner.ainvoke(messages)
            reasoning_content = res_reason.additional_kwargs.get("reasoning_content", "")
            if reasoning_content:
                reasoning_thought = f"【R1 深度推理思考过程】:\n{reasoning_content}\n\n【规划建议】:\n{res_reason.content}"
            else:
                reasoning_thought = res_reason.content
            
            # 打印 R1 推导出的规划建议概要
            await self.send_event("status", f"📋 [复杂规划] R1 思考完毕。推导出的规划建议为：\n{res_reason.content}")
            await self.send_event("status", "📋 [复杂规划] 正在转化为结构化任务链...")
        except Exception as e:
            await self.send_event("status", f"⚠️ [复杂规划] R1 思考时发生异常 ({str(e)})，降级为标准拆解模式...")
            reasoning_thought = "直接根据问题进行结构化拆解。"

        # 2. 将非结构化推理建议转换为 DAGPlan
        llm_structured = self.pipeline.llm_complex.with_structured_output(DAGPlan, method="function_calling")
        
        synthesis_prompt = f"""请根据以下深度思考推导出的规划建议，严格对照图数据库 Schema 生成对应的有向无环图（DAG）任务链 JSON 结构。
请直接将推理得出的思考逻辑填入 `thought` 字段。

【用户的原始问题】：
{rewritten_q}

【R1 深度思考推导的规划建议】：
{reasoning_thought}
"""
        
        messages_structured = [
            SystemMessage(content="You are a schema mapping assistant. Convert the provided unstructured plan and thought process into a structured DAGPlan JSON strictly matching the defined schema."),
            HumanMessage(content=synthesis_prompt)
        ]
        
        try:
            # 首次生成
            plan = await llm_structured.ainvoke(messages_structured)
            errors = validate_dag_plan(plan)
            
            if errors:
                error_msg = "; ".join(errors)
                await self.send_event("status", f"⚠️ [复杂规划] 结构化转换校验未通过: {error_msg}。启动自纠正...")
                
                messages_structured.append(AIMessage(content=plan.model_dump_json()))
                messages_structured.append(HumanMessage(content=f"你生成的计划校验未通过，错误如下：\n{error_msg}\n请结合错误提示重新修正，输出无错的 DAG 计划。"))
                
                plan = await llm_structured.ainvoke(messages_structured)
                errors = validate_dag_plan(plan)
                if errors:
                    raise ValueError(f"二次纠正依旧未通过: {'; '.join(errors)}")
                    
            task_descriptions = []
            for t in plan.tasks:
                args_desc = t.args.model_dump(exclude_none=True) if hasattr(t.args, "model_dump") else t.args
                deps_desc = f" (依赖: {', '.join(t.dependencies)})" if t.dependencies else ""
                task_descriptions.append(f"  - [{t.id}] {t.tool} {args_desc}{deps_desc}")
            tasks_summary = "\n".join(task_descriptions)
            await self.send_event("status", f"📋 [复杂规划] 并行检索计划校验成功。最终生成的子任务链为：\n{tasks_summary}")
            return plan
            
        except Exception as e:
            await self.send_event("status", f"⚠️ [复杂规划] 任务链结构化转换或校验失败：{str(e)}")
            await self.send_event("status", f"📋 [复杂规划] R1 原始推导规划记录以备查考：\n{reasoning_thought}")
            await self.send_event("status", "📋 [复杂规划] 已触发安全兜底策略，使用向量库进行直接检索...")
            # 构造安全兜底计划
            return DAGPlan(
                thought=f"降级策略。原因: {str(e)}",
                tasks=[
                    TaskSpec(
                        id="fallback_task",
                        tool="search_vector_graph_async",
                        args={"query": rewritten_q, "k": 5},
                        dependencies=[]
                    )
                ]
            )


class ResearcherAgent(BaseSubAgent):
    async def research(self, plan: DAGPlan) -> list:
        # 使用并发执行引擎处理有向无环图 (DAG) 任务编排
        raw_results = {}
        task_futures = {}
        observations = []
        
        # 建立工具名称到对应函数实例的映射字典
        tool_map = {
            "query_neo4j_async": query_neo4j_async,
            "get_person_timeline_async": get_person_timeline_async,
            "search_historical_text_async": search_historical_text_async,
            "search_vector_graph_async": search_vector_graph_async
        }
        
        async def execute_dag_node(task_spec: TaskSpec):
            task_id = task_spec.id
            
            # 1. 先等待所有依赖的前置任务执行完毕
            for dep_id in task_spec.dependencies:
                if dep_id in task_futures:
                    await task_futures[dep_id]
                    
            # 2. 动态解析/求值参数中的占位符变量
            args_dict = task_spec.args.model_dump(exclude_none=True) if hasattr(task_spec.args, "model_dump") else task_spec.args
            resolved_args = resolve_args_placeholders(args_dict, raw_results)
            
            tool_name = task_spec.tool
            # 2.2 参数规范化，防御大模型参数幻觉
            if isinstance(resolved_args, dict):
                if tool_name == "search_historical_text_async":
                    for old_k in ["query", "keywords", "text"]:
                        if old_k in resolved_args and "keyword" not in resolved_args:
                            resolved_args["keyword"] = resolved_args.pop(old_k)
                elif tool_name == "get_person_timeline_async":
                    for old_k in ["query", "keyword"]:
                        if old_k in resolved_args and "name" not in resolved_args:
                            resolved_args["name"] = resolved_args.pop(old_k)
                elif tool_name == "search_vector_graph_async":
                    for old_k in ["keyword", "keywords", "text"]:
                        if old_k in resolved_args and "query" not in resolved_args:
                            resolved_args["query"] = resolved_args.pop(old_k)
                            
            config = {"callbacks": [self.pipeline.handler]} if self.pipeline.handler else {}
            
            obs_str = ""
            try:
                await self.send_event("status", f"➡️ [并行检索] 启动 {tool_name} 参数: {resolved_args}")
                tool_func = tool_map.get(tool_name)
                if tool_func:
                    obs_str = await tool_func.ainvoke(resolved_args, config=config)
                else:
                    obs_str = f"Error: Tool '{tool_name}' not found."
            except Exception as e:
                obs_str = f"Error executing tool '{tool_name}': {str(e)}"
                
            # 将原始返回解析并写入全局缓存，供后置依赖使用
            try:
                raw_results[task_id] = json.loads(obs_str)
            except Exception:
                raw_results[task_id] = obs_str
                
            synthesis_obs_str = truncate_tool_output(clean_obs_for_synthesis(obs_str))
            observations.append({
                "tool": tool_name.replace("_async", ""),
                "query": resolved_args,
                "result": synthesis_obs_str
            })
        
        # 将任务包装为 asyncio Task 并行调度，依赖关系会在协程内部自等待
        loop = asyncio.get_running_loop()
        for task_spec in plan.tasks:
            task_futures[task_spec.id] = loop.create_task(execute_dag_node(task_spec))
            
        await asyncio.gather(*task_futures.values())
        return observations


class SynthesisAgent(BaseSubAgent):
    async def synthesize(self, rewritten_q: str, q_type: str, all_observations: list):
        obs_size = len(json.dumps(all_observations, ensure_ascii=False).encode('utf-8'))
        await self.send_event("status", f"✍️ [{self.pipeline.synthesis_agent_name}] 正在考证并合成解答 (获取到 {len(all_observations)} 个子任务结果，共 {obs_size} 字节)...")
        query_failed = False
        last_error = None
        
        for obs in all_observations:
            res_data = obs["result"]
            if "Database query failed permanently" in res_data:
                query_failed = True
                last_error = res_data
            
        # 对搜集到的所有史料进行去重并设置全局硬天花板，防止 token 膨胀
        raw_consolidated = consolidate_and_deduplicate_observations(all_observations)
        consolidated_data = truncate_tool_output(raw_consolidated, max_chars=12000)
        
        answer_prompt = ANSWER_TEMPLATE.format(
            question=rewritten_q,
            graph_results=consolidated_data
        )
        system_content = SYSTEM_PERSONA
        if self.pipeline.user_memory_block:
            system_content = self.pipeline.user_memory_block + "\n" + system_content
        answer_messages = [SystemMessage(content=system_content)]
        for role, content in self.pipeline.history_to_process:
            if role == "user":
                answer_messages.append(HumanMessage(content=content))
            else:
                answer_messages.append(AIMessage(content=content))
        answer_messages.append(HumanMessage(content=answer_prompt))
        
        async for chunk in self.pipeline.llm_complex.astream(answer_messages):
            if chunk.content:
                self.pipeline.collected_text.append(chunk.content)
                await self.send_event("text", chunk.content)


# ----------------- Async Streaming Version (Phase 3) -----------------

class QAStreamPipeline:
    def __init__(self, question: str, history: list[dict], event_callback: Callable[[str, str], Awaitable[None]], handler, user_memory_block: str = None):
        self.question = question
        self.history = history
        self.event_callback = event_callback
        self.handler = handler
        # 【调试开关】暂时禁用长期历史记忆以聚焦独立单次问题。恢复请改回: self.user_memory_block = user_memory_block or ""
        self.user_memory_block = ""
        self.llm_cheap = get_llm("cheap")
        self.llm_complex = get_llm("complex")
        self.collected_text = []
        self.history_to_process = []
        self.history_text = ""
        self.all_observations = []

        # Agent roles names (for status logging)
        self.researcher_agent_name = "史料检索官"
        self.synthesis_agent_name = "主考官幕僚"

        # Instantiate specialized agents
        self.intent_agent = IntentAnalyzerAgent(self)
        self.planner_agent = PlannerAgent(self)
        self.researcher_agent = ResearcherAgent(self)
        self.synthesis_agent = SynthesisAgent(self)

    async def send_event(self, event_type: str, content: str):
        if self.event_callback:
            await self.event_callback(event_type, content)
        if event_type == "status":
            print(f"⚙️ [Agent Status] {content}")
        elif event_type == "text":
            sys.stdout.write(content)
            sys.stdout.flush()

    async def check_characters_exist(self, names: List[str]) -> dict[str, bool]:
        if not names:
            return {}
        cypher = """
        UNWIND $names AS name
        OPTIONAL MATCH (p:Person {name: name})
        WITH name, p IS NOT NULL AS person_exists
        OPTIONAL MATCH (e:Event)
        WHERE e.title CONTAINS name 
           OR e.source_text CONTAINS name 
           OR e.translation CONTAINS name 
           OR e.description CONTAINS name
        WITH name, person_exists, count(e) > 0 AS text_exists
        RETURN name, (person_exists OR text_exists) AS exists
        """
        try:
            results = await run_query_async(cypher, {"names": names})
            return {r["name"]: r["exists"] for r in results}
        except Exception as e:
            await self.send_event("status", f"⚠️ [检查人物] 数据库查询失败 ({str(e)})")
            return {name: True for name in names}

    async def process_history(self):
        # ==========================================
        # 【调试开关】暂时禁用短期对话历史上下文，以专注于单次独立问题的调试
        # 若需要重新启用历史上下文，请删除或注释掉以下两行，并取消下方原逻辑的注释：
        self.history_to_process = []
        self.history_text = "（无历史对话）"
        return
        # ==========================================

    async def execute_pipeline(self) -> str:
        q_type = None
        try:
            await self.process_history()
            analysis = await self.intent_agent.analyze()
            
            await self.send_event("status", f"📋 [意图判定] 分类: {analysis.type} | 重写问题: '{analysis.rewritten_question}'")

            q_type = analysis.type
            rewritten_q = analysis.rewritten_question
            self.rewritten_q = rewritten_q

            # 1.3 处理澄清（Human-in-the-loop）
            if q_type == "clarify":
                clarify_data = {
                    "message": getattr(analysis, "clarify_message", None) or "阁下的提问指代未明，敢问具体所指何事或何人？",
                    "options": getattr(analysis, "clarify_options", None) or []
                }
                await self.send_event("clarify", json.dumps(clarify_data, ensure_ascii=False))
                await self.send_event("text", clarify_data["message"])
                self.collected_text.append(clarify_data["message"])
                return q_type

            # 1.5 验证提及的历史人物是否在图数据库中
            if q_type != "generic_chat" and getattr(analysis, "historical_characters", None):
                missing_chars = [name for name, exists in (await self.check_characters_exist(analysis.historical_characters)).items() if not exists]
                if missing_chars:
                    missing_str = "、".join(missing_chars)
                    await self.send_event("status", f"⚠️ 发现人物不在三国志中: {missing_str}")
                    answer = f"抱歉，正史《三国志》中并未记载有关“{missing_str}”的任何信息。此人或非三国时期人物，或在《三国志》中无传无载，老夫无从考证。"
                    await self.send_event("text", answer)
                    self.collected_text.append(answer)
                    return q_type

            # 2a. 闲聊 / 会话历史查询
            if q_type == "generic_chat":
                await self.intent_agent.handle_generic_chat()
                return q_type

            # 2b. 复杂问答逻辑
            if q_type == "complex":
                plan = await self.planner_agent.plan(rewritten_q)
                observations = await self.researcher_agent.research(plan)
                self.all_observations.extend(observations)

            # 2.5 检查是否检索到任何有效的数据库记录，若无，则启动向量库进行兜底
            if not has_valid_db_records(self.all_observations, rewritten_q):
                await self.send_event("status", "⚠️ 未检索到任何有效的 Neo4j 数据库记录，启动向量库进行兜底检索...")
                config = {"callbacks": [self.handler]} if self.handler else {}
                try:
                    fallback_obs = await search_vector_graph_async.ainvoke({"query": rewritten_q, "k": 8}, config=config)
                    synthesis_obs_str = truncate_tool_output(clean_obs_for_synthesis(fallback_obs))
                    self.all_observations.append({
                        "tool": "search_vector_graph",
                        "query": {"query": rewritten_q, "k": 8},
                        "result": synthesis_obs_str
                    })
                except Exception as e:
                    await self.send_event("status", f"⚠️ 向量库兜底检索失败: {str(e)}")

                if not has_valid_db_records(self.all_observations, rewritten_q):
                    await self.send_event("status", "⚠️ 向量库检索也未找到任何有效记录，直接拒绝回答。")
                    answer = "抱歉，在正史《三国志》及相关史料库中未搜寻到任何与该问题相关的史实记录，老夫无从考证。"
                    await self.send_event("text", answer)
                    self.collected_text.append(answer)
                    return q_type

            # 3. 最终汇总与答复
            await self.synthesis_agent.synthesize(rewritten_q, q_type, self.all_observations)

        except Exception as e:
            print(f"Error in pipeline: {str(e)}")
            await self.send_event("status", f"⚠️ 发生系统性故障: {str(e)}")
            err_ans = "（老夫近日因病体抱恙，实在无力翻检书箧。望阁下稍候再问。）"
            self.collected_text.append(err_ans)
            await self.send_event("text", err_ans)
        
        return q_type


async def ask_question_stream(
    question: str, 
    history: list[dict] = None, 
    dataset_item_id: str = None,
    trace_metadata: dict = None,
    user_memory_block: str = None
) -> AsyncGenerator[str, None]:
    """
    异步流式发生器：使用 asyncio.Queue 在生产者线程与消费者生成器之间通信，
    支持实时上报思索轨迹（status）与打字机文本（text）。
    """
    # 0. Check Semantic Cache
    if not dataset_item_id:
        cached_ans, similarity = lookup_cache(question)
        if cached_ans:
            print(f"⚡ [语义缓存] 命中缓存 (相似度: {similarity * 100:.1f}%)，流式返回历史回答。")
            yield json.dumps({"type": "status", "content": f"⚡ [语义缓存] 发现高度匹配的历史解答 (相似度: {similarity * 100:.1f}%)，正在调阅历史答案..."}) + "\n"
            chunk_size = 15
            for i in range(0, len(cached_ans), chunk_size):
                chunk = cached_ans[i:i+chunk_size]
                yield json.dumps({"type": "text", "content": chunk}) + "\n"
                await asyncio.sleep(0.01)
            yield json.dumps({"type": "done", "content": ""}) + "\n"
            return

    langfuse_client = Langfuse()
    trace = langfuse_client.trace(name="qa_pipeline", input=question, dataset_item_id=dataset_item_id)
    if trace_metadata is not None:
        trace_metadata["trace_id"] = trace.id
        
    handler = trace.get_langchain_handler()
    token = active_callback_var.set(handler)
    queue = asyncio.Queue()
    
    async def put_event(event_type: str, content: str):
        await queue.put({"type": event_type, "content": content})
        
    pipeline = QAStreamPipeline(
        question=question,
        history=history,
        event_callback=put_event,
        handler=handler,
        user_memory_block=user_memory_block
    )
    send_event_token = active_send_event_var.set(pipeline.send_event)

    async def run_pipeline():
        try:
            await pipeline.execute_pipeline()
            rewritten_q = getattr(pipeline, "rewritten_q", question)
            final_ans = "".join(pipeline.collected_text)
            
            total_obs_bytes = len(json.dumps(pipeline.all_observations, ensure_ascii=False).encode('utf-8'))
            await put_event("status", f"📊 [地图事件提取] 准备分析候选事件。 observations 数量: {len(pipeline.all_observations)}, 总大小: {total_obs_bytes} 字节。")
            
            extraction_logs = []
            def sync_log(msg: str):
                extraction_logs.append(msg)
                
            extracted_events = extract_events_from_observations(
                pipeline.all_observations,
                rewritten_q,
                final_ans,
                log_func=sync_log
            )
            
            for log_msg in extraction_logs:
                await put_event("status", f"📊 [地图事件提取] {log_msg}")
                
            if extracted_events:
                await put_event("status", f"📊 [地图事件提取] 成功提取出 {len(extracted_events)} 个关联地图事件，正在向前端推送地图渲染。")
                await put_event("events", json.dumps(extracted_events, ensure_ascii=False))
            else:
                await put_event("status", f"📊 [地图事件提取] 未提取出任何满足相关度阈值 (>= 0.15) 的地图事件。")
        finally:
            await queue.put(None)
            ans_str = "".join(pipeline.collected_text)
            langfuse_client.flush()
            if not dataset_item_id:
                save_cache(question, ans_str)
            print("\n")

    producer_task = asyncio.create_task(run_pipeline())

    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield json.dumps(event, ensure_ascii=False) + "\n"
            
        if producer_task.done() and not producer_task.cancelled():
            exc = producer_task.exception()
            if exc:
                raise exc
    finally:
        if not producer_task.done():
            producer_task.cancel()
            try:
                await producer_task
            except asyncio.CancelledError:
                pass
        active_callback_var.reset(token)
        if send_event_token:
            active_send_event_var.reset(send_event_token)


def ask_question(
    question: str, 
    history: list[dict] = None, 
    dataset_item_id: str = None,
    trace_metadata: dict = None,
    user_memory_block: str = None
) -> str:
    """
    同步版本的问答接口，方便在非异步环境或测试中调用。
    """
    async def _run():
        chunks = []
        async for raw_chunk in ask_question_stream(
            question, 
            history, 
            dataset_item_id=dataset_item_id, 
            trace_metadata=trace_metadata,
            user_memory_block=user_memory_block
        ):
            try:
                chunk = json.loads(raw_chunk)
                if chunk.get("type") == "text":
                    chunks.append(chunk.get("content", ""))
            except Exception:
                pass
        return "".join(chunks)
    
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    if loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, _run())
            return future.result()
    else:
        return loop.run_until_complete(_run())


if __name__ == "__main__":
    async def run_main():
        async for chunk in ask_question_stream("分析曹操在官渡之战前后的战略调整"):
            print(chunk.strip())
            
    asyncio.run(run_main())
