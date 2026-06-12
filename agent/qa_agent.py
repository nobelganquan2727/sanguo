import os
import sys
import json
import asyncio
from pydantic import BaseModel, Field
from typing import List, Literal, AsyncGenerator

# 让脚本可以直接通过 python3 agent/qa_agent.py 运行
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from dotenv import load_dotenv
from agent.prompts import (
    SYSTEM_PERSONA,
    MEM_SUMMARY_PROMPT,
    AGENT_SYSTEM_PROMPT,
    PLANNING_PROMPT,
    INTENT_ANALYSIS_SYSTEM,
    INTENT_ANALYSIS_PROMPT,
    CYPHER_GENERATION_TEMPLATE,
    ANSWER_RELATIONSHIP_TEMPLATE,
    ANSWER_FACT_TEMPLATE,
    ANSWER_PLANNING_TEMPLATE,
    get_relevant_few_shots
)
from agent.observability import AgentObservabilityCallbackHandler, active_callback_var
from agent.cache import lookup_cache, save_cache
from agent.graph_client import run_query

load_dotenv()

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



def has_valid_db_records(observations: list) -> bool:
    if not observations:
        return False
    for obs in observations:
        res = obs.get("result", "").strip()
        if not res:
            continue
        if "未找到" in res:
            continue
        if res == "[]":
            continue
        if "Error executing" in res or "Database query failed" in res:
            continue
        try:
            parsed = json.loads(res)
            if isinstance(parsed, list) and len(parsed) == 0:
                continue
        except Exception:
            pass
        return True
    return False

# ----------------- Async Streaming Version (Phase 3) -----------------

async def ask_question_stream(question: str, history: list[dict] = None) -> AsyncGenerator[str, None]:
    """
    异步流式发生器：使用 asyncio.Queue 在生产者线程与消费者生成器之间通信，
    支持实时上报思索轨迹（status）与打字机文本（text）。
    """
    send_event_token = None
    # 0. Check Semantic Cache
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

    handler = AgentObservabilityCallbackHandler()
    token = active_callback_var.set(handler)
    
    llm_cheap = get_llm("cheap")
    llm_complex = get_llm("complex")
    queue = asyncio.Queue()

    async def send_event(event_type: str, content: str):
        await queue.put({"type": event_type, "content": content})
        if event_type == "status":
            print(f"⚙️ [Agent Status] {content}")
        elif event_type == "text":
            sys.stdout.write(content)
            sys.stdout.flush()

    send_event_token = active_send_event_var.set(send_event)

    async def check_characters_exist_async(names: List[str]) -> dict[str, bool]:
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
            await send_event("status", f"⚠️ [检查人物] 数据库查询失败 ({str(e)})")
            return {name: True for name in names}

    async def run_agent_loop_async(llm_with_tools, rewritten_q: str, history_text: str) -> list:
        handler = active_callback_var.get()
        config = {"callbacks": [handler]} if handler else {}
        agent_messages = [
            SystemMessage(content=AGENT_SYSTEM_PROMPT),
            HumanMessage(content=f"历史对话与摘要：\n{history_text}\n\n当前查询任务：\n{rewritten_q}")
        ]
        observations = []
        max_steps = 5
        step = 0
        
        while step < max_steps:
            await send_event("status", f"🤖 [幕僚思考中] 正在研判下一步行动 (第 {step+1} 步)...")
            try:
                response = await llm_with_tools.ainvoke(agent_messages)
            except Exception as e:
                await send_event("status", f"⚠️ 研判出现故障: {str(e)}")
                break
                
            agent_messages.append(response)
            
            if not response.tool_calls:
                await send_event("status", "🤖 [幕僚] 研判结束，已搜集到足够卷宗数据。")
                break
                
            tool_names = [tc['name'] for tc in response.tool_calls]
            await send_event("status", f"🤖 [幕僚] 决定翻检对应史书，调用工具: {tool_names}")
            
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
                    
                await send_event("status", f"📊 [卷宗调阅] {tool_name} 返回了 {len(obs_str)} 字节的历史记录")
                
                observations.append({
                    "tool": tool_name.replace("_async", ""),
                    "query": tool_args,
                    "result": obs_str
                })
                
                agent_messages.append(ToolMessage(content=obs_str, tool_call_id=tool_id))
                
            step += 1
            
        return observations

    async def producer():
        collected_text = []
        q_type = None
        try:
            # 0. 对话历史解析与记忆压缩
            history_to_process = []
            if history:
                for msg in history:
                    role = msg.get("role")
                    content = msg.get("content")
                    if role in ("user", "ai", "assistant") and content:
                        history_to_process.append((role, content))
                
                if history_to_process and history_to_process[-1][0] == "user" and history_to_process[-1][1] == question:
                    history_to_process.pop()
                    
                history_to_process = history_to_process[-20:]

            history_summary = ""
            recent_messages = history_to_process
            
            if len(history_to_process) > 6:
                await send_event("status", "📝 [记忆整理] 对话历史较长，正在提炼前文要旨...")
                older_messages = history_to_process[:-4]
                recent_messages = history_to_process[-4:]
                
                older_text = "\n".join([f"{'用户' if r == 'user' else 'AI'}: {c}" for r, c in older_messages])
                summary_prompt = MEM_SUMMARY_PROMPT.format(history_text=older_text)
                try:
                    summary_res = await llm_cheap.ainvoke([HumanMessage(content=summary_prompt)])
                    history_summary = summary_res.content.strip()
                    await send_event("status", f"📝 [记忆整理] 提炼完毕: '{history_summary}'")
                except Exception as e:
                    await send_event("status", f"⚠️ 提炼失败: {str(e)}，将使用未压缩历史。")
                    history_summary = ""
                    recent_messages = history_to_process

            if history_summary:
                history_text = f"=== 历史对话摘要 ===\n{history_summary}\n\n"
            else:
                history_text = ""
                
            history_text += "\n".join([f"{'用户' if r == 'user' else 'AI'}: {c}" for r, c in recent_messages])
            if not history_text:
                history_text = "（无历史对话）"

            # 1. 意图拆解与代词消解
            await send_event("status", "🧠 [意图拆解] 正在分析问题意图并消解上下文代词...")
            analysis = None
            try:
                structured_llm = llm_cheap.with_structured_output(IntentAnalysis, method="function_calling")
                analysis_messages = [
                    SystemMessage(content=INTENT_ANALYSIS_SYSTEM),
                    HumanMessage(content=INTENT_ANALYSIS_PROMPT.format(history_text=history_text, question=question))
                ]
                analysis = await structured_llm.ainvoke(analysis_messages)
            except Exception as e:
                await send_event("status", f"⚠️ [意图拆解] structured_output 失败 ({str(e)})，正在尝试原生 JSON 兜底。")
                try:
                    fallback_prompt = INTENT_ANALYSIS_PROMPT.format(history_text=history_text, question=question) + "\n请返回一个符合上述 JSON schema 的对象（确保不要用 markdown 代码块标记，只输出 JSON 文本）。"
                    res_msg = await llm_cheap.ainvoke([
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
                        rewritten_question=data.get("rewritten_question", question),
                        entities=data.get("entities", []),
                        historical_characters=data.get("historical_characters", [])
                    )
                except Exception as e2:
                    await send_event("status", f"⚠️ [意图拆解] 兜底解析失败 ({str(e2)})，退水至经验规则分类。")
                    q_type = "fact"
                    if any(w in question for w in ["关系", "交集", "纠葛", "对比", "和"]):
                        q_type = "relationship"
                    elif any(w in question for w in ["刚才", "之前", "什么", "谁", "你好", "哈喽"]):
                        if "刚才" in question or "之前" in question:
                            q_type = "generic_chat"
                    analysis = IntentAnalysis(
                        type=q_type,
                        rewritten_question=question,
                        entities=[],
                        historical_characters=[]
                    )
                    
            await send_event("status", f"📋 [意图判定] 分类: {analysis.type} | 重写问题: '{analysis.rewritten_question}'")

            q_type = analysis.type
            rewritten_q = analysis.rewritten_question

            # 1.5 验证提及的历史人物是否在图数据库中
            if q_type != "generic_chat" and getattr(analysis, "historical_characters", None):
                missing_chars = [name for name, exists in (await check_characters_exist_async(analysis.historical_characters)).items() if not exists]
                if missing_chars:
                    missing_str = "、".join(missing_chars)
                    await send_event("status", f"⚠️ 发现人物不在三国志中: {missing_str}")
                    answer = f"抱歉，正史《三国志》中并未记载有关“{missing_str}”的任何信息。此人或非三国时期人物，或在《三国志》中无传无载，老夫无从考证。"
                    await send_event("text", answer)
                    collected_text.append(answer)
                    return

            # 2a. 闲聊 / 会话历史查询
            if q_type == "generic_chat":
                await send_event("status", "💬 [闲聊回答] 无需翻检古籍，正在直接答复...")
                chat_messages = [SystemMessage(content=f"{SYSTEM_PERSONA}请根据用户的当前问题和对话历史进行回答。")]
                for role, content in history_to_process:
                    if role == "user":
                        chat_messages.append(HumanMessage(content=content))
                    else:
                        chat_messages.append(AIMessage(content=content))
                chat_messages.append(HumanMessage(content=question))
                
                async for chunk in llm_cheap.astream(chat_messages):
                    if chunk.content:
                        collected_text.append(chunk.content)
                        await send_event("text", chunk.content)
                return

            tools_async = [query_neo4j_async, get_person_timeline_async, search_historical_text_async, search_vector_graph_async]
            llm_with_tools_async = llm_complex.bind_tools(tools_async)
            all_observations = []

            # 2b. 复杂计划型查询拆解 (Plan-and-Solve)
            if q_type == "complex_planning":
                await send_event("status", "📋 [复杂规划] 提问宏观，正在将其拆解为多个子课题...")
                planning_prompt_formatted = PLANNING_PROMPT.format(question=rewritten_q)
                sub_queries = []
                try:
                    plan_msg = await llm_complex.ainvoke([
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
                    await send_event("status", f"⚠️ [复杂规划] 拆解失败 ({str(e)})，降级至单轮处理。")
                    sub_queries = [rewritten_q]
                    
                await send_event("status", f"📋 [复杂规划] 拆解计划: {sub_queries}")
                
                for idx, sq in enumerate(sub_queries):
                    await send_event("status", f"➡️ [课题 {idx+1}/{len(sub_queries)}] 正在搜集: '{sq}'...")
                    sq_obs = await run_agent_loop_async(llm_with_tools_async, sq, history_text)
                    all_observations.extend(sq_obs)
                    
            # 2c. 常规事实或关系查询
            else:
                all_observations = await run_agent_loop_async(llm_with_tools_async, rewritten_q, history_text)

            # 2.5 检查是否检索到任何有效的数据库记录
            if not has_valid_db_records(all_observations):
                await send_event("status", "⚠️ 未检索到任何有效的 Neo4j 数据库记录，直接拒绝回答。")
                answer = "抱歉，在正史《三国志》及相关史料库中未搜寻到任何与该问题相关的史实记录，老夫无从考证。"
                await send_event("text", answer)
                collected_text.append(answer)
                return

            # 3. 汇总数据与自检故障
            await send_event("status", "✍️ 正在汇编并考证所有搜集到的史料，准备作答...")
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

            answer_messages = [SystemMessage(content=SYSTEM_PERSONA)]
            for role, content in history_to_process:
                if role == "user":
                    answer_messages.append(HumanMessage(content=content))
                else:
                    answer_messages.append(AIMessage(content=content))
            answer_messages.append(HumanMessage(content=answer_prompt))
            
            # 使用流式接口 astream 输出最终回答
            async for chunk in llm_complex.astream(answer_messages):
                if chunk.content:
                    collected_text.append(chunk.content)
                    await send_event("text", chunk.content)

        except Exception as e:
            print(f"Error in producer: {str(e)}")
            await send_event("status", f"⚠️ 发生系统性故障: {str(e)}")
            err_ans = "（老夫近日因病体抱恙，实在无力翻检书箧。望阁下稍候再问。）"
            collected_text.append(err_ans)
            await send_event("text", err_ans)
        finally:
            # 先关流，再做慢速清理（save_cache 调 embedding API 会阻塞）
            await queue.put(None)
            ans_str = "".join(collected_text)
            handler.finalize_run(question, ans_str, q_type)
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
        active_callback_var.reset(token)
        if send_event_token:
            active_send_event_var.reset(send_event_token)

def ask_question(question: str, history: list[dict] = None) -> str:
    """
    同步版本的问答接口，方便在非异步环境或测试中调用。
    """
    async def _run():
        chunks = []
        async for raw_chunk in ask_question_stream(question, history):
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
