import os
import sys
import json
import asyncio
from pydantic import BaseModel, Field
from typing import List, Literal, AsyncGenerator

# 让脚本可以直接通过 python3 agent/qa_agent.py 运行
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from dotenv import load_dotenv
from agent.prompts import (
    SYSTEM_PERSONA,
    get_system_persona,
    MEM_SUMMARY_PROMPT,
    AGENT_SYSTEM_PROMPT,
    PLANNING_PROMPT,
    INTENT_ANALYSIS_SYSTEM,
    INTENT_ANALYSIS_PROMPT,
    ANSWER_RELATIONSHIP_TEMPLATE,
    ANSWER_FACT_TEMPLATE,
    ANSWER_PLANNING_TEMPLATE
)
from agent.observability import active_callback_var
from agent.cache import lookup_cache, save_cache
from agent.utils import has_valid_db_records, extract_events_from_observations

load_dotenv()
from langfuse import Langfuse

from agent.tools import (
    get_llm,
    query_neo4j_async,
    get_person_timeline_async,
    search_historical_text_async,
    search_vector_graph_async,
    active_send_event_var,
    run_query_async
)


class IntentAnalysis(BaseModel):
    type: Literal["relationship", "fact", "generic_chat", "complex_planning"] = Field(
        description="意图类型。relationship用于人物交集/对比/关联；fact用于特定单一史实/生平查询；generic_chat用于日常问候与闲聊；complex_planning用于需要拆解为多步查询的宏观或复杂历史提问（如官渡之战前后战略调整）。"
    )
    rewritten_question: str = Field(
        description="结合历史对话重写后的独立且完整的明确提问，若原句有代词或指代不清应消解代词并还原完整上下文。"
    )
    entities: List[str] = Field(
        description="问题中包含的核心历史人物、官职或地点。"
    )
    historical_characters: List[str] = Field(
        default_factory=list,
        description="重写后问题中显式提到的具体三国历史人物或虚构人物名字（例如：['曹操', '刘备']，或 ['哈利波特']）。如果没有具体人名，则为空列表。"
    )


class BaseSubAgent:
    def __init__(self, pipeline: 'QAStreamPipeline'):
        self.pipeline = pipeline

    async def send_event(self, event_type: str, content: str):
        await self.pipeline.send_event(event_type, content)

class IntentAnalyzerAgent(BaseSubAgent):
    async def analyze(self) -> IntentAnalysis:
        await self.send_event("status", "🧠 [意图拆解] 正在分析问题意图并消解上下文代词...")
        analysis = None
        try:
            structured_llm = self.pipeline.llm_cheap.with_structured_output(IntentAnalysis, method="function_calling")
            analysis_messages = [
                SystemMessage(content=INTENT_ANALYSIS_SYSTEM),
                HumanMessage(content=INTENT_ANALYSIS_PROMPT.format(history_text=self.pipeline.history_text, question=self.pipeline.question))
            ]
            analysis = await structured_llm.ainvoke(analysis_messages)
        except Exception as e:
            await self.send_event("status", f"⚠️ [意图拆解] structured_output 失败 ({str(e)})，正在尝试原生 JSON 兜底。")
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
                    type=data.get("type", "fact"),
                    rewritten_question=data.get("rewritten_question", self.pipeline.question),
                    entities=data.get("entities", []),
                    historical_characters=data.get("historical_characters", [])
                )
            except Exception as e2:
                await self.send_event("status", f"⚠️ [意图拆解] 兜底解析失败 ({str(e2)})，退水至经验规则分类。")
                q_type = "fact"
                if any(w in self.pipeline.question for w in ["关系", "交集", "纠葛", "对比", "和"]):
                    q_type = "relationship"
                elif any(w in self.pipeline.question for w in ["刚才", "之前", "什么", "谁", "你好", "哈喽"]):
                    if "刚才" in self.pipeline.question or "之前" in self.pipeline.question:
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
        system_content = f"{get_system_persona(self.pipeline.question)}请根据用户的当前问题和对话历史进行回答。"
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
    async def plan(self, rewritten_q: str) -> List[str]:
        await self.send_event("status", "📋 [复杂规划] 提问宏观，正在将其拆解为多个子课题...")
        planning_prompt_formatted = PLANNING_PROMPT.format(question=rewritten_q)
        sub_queries = []
        try:
            plan_msg = await self.pipeline.llm_complex.ainvoke([
                SystemMessage(content="You are a planning assistant. Output JSON only matching the schema."),
                HumanMessage(content=planning_prompt_formatted)
            ])
            plan_res = plan_msg.content.strip()
            
            if plan_res.startswith("```json"):
                plan_res = plan_res[7:]
            elif plan_res.startswith("```"):
                plan_res = plan_res[3:]
            if plan_res.endswith("```"):
                plan_res = plan_res[:-3]
            plan_res = plan_res.strip()
            
            sub_queries = json.loads(plan_res).get("sub_queries", [])
        except Exception as e:
            await self.send_event("status", f"⚠️ [复杂规划] 拆解失败 ({str(e)})，降级至单轮处理。")
            sub_queries = [rewritten_q]
            
        await self.send_event("status", f"📋 [复杂规划] 拆解计划: {sub_queries}")
        return sub_queries

class ResearcherAgent(BaseSubAgent):
    async def research(self, rewritten_q: str) -> list:
        config = {"callbacks": [self.pipeline.handler]} if self.pipeline.handler else {}
        system_content = AGENT_SYSTEM_PROMPT
        if self.pipeline.user_memory_block:
            system_content = self.pipeline.user_memory_block + "\n" + system_content
        agent_messages = [
            SystemMessage(content=system_content),
            HumanMessage(content=f"历史对话与摘要：\n{self.pipeline.history_text}\n\n当前查询任务：\n{rewritten_q}")
        ]
        observations = []
        max_steps = 5
        step = 0
        
        tools_async = [query_neo4j_async, get_person_timeline_async, search_historical_text_async, search_vector_graph_async]
        llm_with_tools_async = self.pipeline.llm_complex.bind_tools(tools_async)
        
        while step < max_steps:
            await self.send_event("status", f"🤖 [{self.pipeline.researcher_agent_name}] 正在研判下一步行动 (第 {step+1} 步)...")
            try:
                response = await llm_with_tools_async.ainvoke(agent_messages)
            except Exception as e:
                await self.send_event("status", f"⚠️ 研判出现故障: {str(e)}")
                break
                
            agent_messages.append(response)
            
            if not response.tool_calls:
                await self.send_event("status", f"🤖 [{self.pipeline.researcher_agent_name}] 研判结束，已搜集到足够卷宗数据。")
                break
                
            tool_names = [tc['name'] for tc in response.tool_calls]
            await self.send_event("status", f"🤖 [{self.pipeline.researcher_agent_name}] 决定翻检对应史书，调用工具: {tool_names}")
            
            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                tool_id = tool_call["id"]
                
                obs_str = ""
                try:
                    if tool_name == "query_neo4j_async":
                        obs_str = await query_neo4j_async.ainvoke(tool_args, config=config)
                    elif tool_name == "get_person_timeline_async":
                        obs_str = await get_person_timeline_async.ainvoke(tool_args, config=config)
                    elif tool_name == "search_historical_text_async":
                        obs_str = await search_historical_text_async.ainvoke(tool_args, config=config)
                    elif tool_name == "search_vector_graph_async":
                        obs_str = await search_vector_graph_async.ainvoke(tool_args, config=config)
                    else:
                        obs_str = f"Error: Tool '{tool_name}' not found."
                except Exception as e:
                    obs_str = f"Error executing tool '{tool_name}': {str(e)}"
                    
                await self.send_event("status", f"📊 [卷宗调阅] {tool_name} 返回了 {len(obs_str)} 字节的历史记录")
                
                observations.append({
                    "tool": tool_name.replace("_async", ""),
                    "query": tool_args,
                    "result": obs_str
                })
                
                agent_messages.append(ToolMessage(content=obs_str, tool_call_id=tool_id))
                
            step += 1
            
        return observations

class SynthesisAgent(BaseSubAgent):
    async def synthesize(self, rewritten_q: str, q_type: str, all_observations: list):
        await self.send_event("status", f"✍️ [{self.pipeline.synthesis_agent_name}] 正在汇编并考证所有搜集到的史料，准备作答...")
        formatted_data = []
        query_failed = False
        last_error = None
        
        for obs in all_observations:
            res_data = obs["result"]
            if "Database query failed permanently" in res_data:
                query_failed = True
                last_error = res_data
            formatted_data.append(f"【工具: {obs['tool']} | 查询参数: {obs['query']}】\n数据: {res_data}")
            
        consolidated_data = "\n\n".join(formatted_data)
        
        if q_type == "complex_planning":
            answer_prompt = ANSWER_PLANNING_TEMPLATE.format(
                question=rewritten_q,
                graph_results=consolidated_data
            )
        elif q_type == "relationship":
            answer_prompt = ANSWER_RELATIONSHIP_TEMPLATE.format(
                question=rewritten_q,
                graph_results=consolidated_data
            )
        else:
            answer_prompt = ANSWER_FACT_TEMPLATE.format(
                question=rewritten_q,
                graph_results=consolidated_data
            )

        if query_failed or not all_observations:
            err_msg = last_error if query_failed else "未找到可用史料"
            answer_prompt += f"\n\n【注意】由于当前“简牍翻阅多有不便”（底盘检索阻碍：{err_msg}），藏书阁中暂未寻得详尽佐证。请基于你自身强大的《三国志》真实正史知识，直接对用户问题做出详实解答，并合理进行学者推演（回答中需隐晦体现因古籍翻阅不便而自行考证，严禁透露任何技术故障词汇）。"

        system_content = get_system_persona(rewritten_q)
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
    def __init__(self, question: str, history: list[dict], queue: asyncio.Queue, handler, user_memory_block: str = None):
        self.question = question
        self.history = history
        self.queue = queue
        self.handler = handler
        self.user_memory_block = user_memory_block or ""
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
        await self.queue.put({"type": event_type, "content": content})
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
        if self.history:
            for msg in self.history:
                role = msg.get("role")
                content = msg.get("content")
                if role in ("user", "ai", "assistant") and content:
                    self.history_to_process.append((role, content))
            
            if self.history_to_process and self.history_to_process[-1][0] == "user" and self.history_to_process[-1][1] == self.question:
                self.history_to_process.pop()
                
            self.history_to_process = self.history_to_process[-20:]

        history_summary = ""
        recent_messages = self.history_to_process
        
        if len(self.history_to_process) > 6:
            await self.send_event("status", "📝 [记忆整理] 对话历史较长，正在提炼前文要旨...")
            older_messages = self.history_to_process[:-4]
            recent_messages = self.history_to_process[-4:]
            
            older_text = "\n".join([f"{'用户' if r == 'user' else 'AI'}: {c}" for r, c in older_messages])
            summary_prompt = MEM_SUMMARY_PROMPT.format(history_text=older_text)
            try:
                summary_res = await self.llm_cheap.ainvoke([HumanMessage(content=summary_prompt)])
                history_summary = summary_res.content.strip()
                await self.send_event("status", f"📝 [记忆整理] 提炼完毕: '{history_summary}'")
            except Exception as e:
                await self.send_event("status", f"⚠️ 提炼失败: {str(e)}，将使用未压缩历史。")
                history_summary = ""
                recent_messages = self.history_to_process

        if history_summary:
            self.history_text = f"=== 历史对话摘要 ===\n{history_summary}\n\n"
        else:
            self.history_text = ""
            
        self.history_text += "\n".join([f"{'用户' if r == 'user' else 'AI'}: {c}" for r, c in recent_messages])
        if not self.history_text:
            self.history_text = "（无历史对话）"

    async def execute_pipeline(self) -> str:
        q_type = None
        try:
            await self.process_history()
            analysis = await self.intent_agent.analyze()
            
            await self.send_event("status", f"📋 [意图判定] 分类: {analysis.type} | 重写问题: '{analysis.rewritten_question}'")

            q_type = analysis.type
            rewritten_q = analysis.rewritten_question
            self.rewritten_q = rewritten_q

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

            # 2b. 复杂计划型查询拆解 (Plan-and-Solve)
            if q_type == "complex_planning":
                sub_queries = await self.planner_agent.plan(rewritten_q)
                for idx, sq in enumerate(sub_queries):
                    await self.send_event("status", f"➡️ [课题 {idx+1}/{len(sub_queries)}] 正在搜集: '{sq}'...")
                    sq_obs = await self.researcher_agent.research(sq)
                    self.all_observations.extend(sq_obs)
            else:
                self.all_observations = await self.researcher_agent.research(rewritten_q)

            # 2.5 检查是否检索到任何有效的数据库记录
            if not has_valid_db_records(self.all_observations):
                await self.send_event("status", "⚠️ 未检索到任何有效的 Neo4j 数据库记录，直接拒绝回答。")
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
    # 0. Check Semantic Cache (Bypass when running evaluations/dataset runs)
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
    
    pipeline = QAStreamPipeline(question, history, queue, handler, user_memory_block=user_memory_block)
    send_event_token = active_send_event_var.set(pipeline.send_event)

    async def producer():
        q_type = None
        try:
            q_type = await pipeline.execute_pipeline()
            # Extract events and emit as 'events' chunk
            rewritten_q = getattr(pipeline, "rewritten_q", question)
            final_ans = "".join(pipeline.collected_text)
            extracted_events = extract_events_from_observations(pipeline.all_observations, rewritten_q, final_ans)
            if extracted_events:
                await queue.put({"type": "events", "content": json.dumps(extracted_events, ensure_ascii=False)})
        finally:
            await queue.put(None)
            ans_str = "".join(pipeline.collected_text)
            langfuse_client.flush()
            # Don't save to cache during evaluation runs
            if not dataset_item_id:
                save_cache(question, ans_str)
            print("\n")

    try:
        producer_task = asyncio.create_task(producer())

        while True:
            event = await queue.get()
            if event is None:
                break
            yield json.dumps(event, ensure_ascii=False) + "\n"
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
