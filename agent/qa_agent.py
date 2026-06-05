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
from agent.schema import GRAPH_SCHEMA
from agent.graph_client import run_query
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

load_dotenv()

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

def get_llm(model_type: str = "complex"):
    handler = active_callback_var.get()
    callbacks = [handler] if handler else []
    
    if model_type == "cheap":
        return ChatOpenAI(
            model="qwen-plus",
            api_key=os.environ.get("DASHSCOPE_API_KEY"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            temperature=0,
            callbacks=callbacks
        )
    else:
        return ChatOpenAI(
            model="deepseek-chat", 
            api_key=os.environ.get("DEEPSEEK_API_KEY"), 
            base_url="https://api.deepseek.com/v1",
            max_tokens=8192,
            temperature=0,
            callbacks=callbacks
        )

def truncate_tool_output(output: str, max_chars: int = 3000) -> str:
    if len(output) > max_chars:
        return output[:max_chars] + f"\n\n【卷宗纪要说明】此处史料文字过长已作删减，仅展示前文{max_chars}字。若仍需深究，请缩窄检索条件重新调阅。"
    return output

def check_characters_exist(names: List[str]) -> dict[str, bool]:
    if not names:
        return {}
    cypher = "UNWIND $names AS name OPTIONAL MATCH (p:Person {name: name}) RETURN name, p IS NOT NULL AS exists"
    try:
        results = run_query(cypher, {"names": names})
        return {r["name"]: r["exists"] for r in results}
    except Exception as e:
        print(f"⚠️ 检查人物是否存在时出错: {e}")
        return {name: True for name in names}

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

# ----------------- Tools Definition (Sync) -----------------

@tool
def query_neo4j(cypher: str) -> str:
    """执行 Neo4j Cypher 语句查询图数据库。当你需要复杂的图关系、多度查询或高度定制化的匹配时使用。参数 cypher 必须是合法的 Cypher 语句。"""
    llm = get_llm()
    max_retries = 2
    retry_count = 0
    last_error = None
    
    execution_messages = [
        SystemMessage(content=SYSTEM_PERSONA),
        SystemMessage(content=GRAPH_SCHEMA),
        HumanMessage(content=f"请生成或执行以下查询所需的最合理的 Cypher：\n{cypher}")
    ]
    
    current_cypher = cypher
    
    while retry_count <= max_retries:
        if retry_count > 0:
            print(f"🔄 [query_neo4j Tool] 正在尝试第 {retry_count} 次自修正 Cypher...")
            correction_prompt = f"""
上一次执行生成的 Cypher 语句时数据库报错了。

【错误信息】：
{last_error}

【当时生成的 Cypher】：
{current_cypher}

请仔细对照 Schema 修正语法或逻辑错误。请直接输出修正后的 Cypher 查询语句，不要有任何其他解释，不要用 markdown 代码块标记，直接输出纯文本。
"""
            execution_messages.append(AIMessage(content=current_cypher))
            execution_messages.append(HumanMessage(content=correction_prompt))
            current_cypher = llm.invoke(execution_messages).content.strip()
            
            # Clean markdown codeblock
            if current_cypher.startswith("```cypher"):
                current_cypher = current_cypher[9:]
            elif current_cypher.startswith("```"):
                current_cypher = current_cypher[3:]
            if current_cypher.endswith("```"):
                current_cypher = current_cypher[:-3]
            current_cypher = current_cypher.strip()

        print(f"🔍 [query_neo4j Tool] [尝试 {retry_count + 1}] 执行 Cypher: \n{current_cypher}\n")
        try:
            results = run_query(current_cypher)
            return truncate_tool_output(json.dumps(results, ensure_ascii=False))
        except Exception as e:
            last_error = str(e)
            print(f"⚠️ [query_neo4j Tool] 第 {retry_count + 1} 次查询失败: {last_error}")
            retry_count += 1
            
    return f"Error executing Cypher query after retries: {last_error}"

@tool
def get_person_timeline(name: str) -> str:
    """获取特定三国历史人物的生平事件时间线。参数 name 是历史人物的中文名（例如 '曹操', '刘备', '徐晃'）。返回按时间顺序排列的事件列表。"""
    cypher = """
    MATCH (p:Person {name: $name})-[:PARTICIPATED_IN]->(e:Event)
    RETURN e.title AS title, e.description AS description, e.time_text AS time, e.std_start_year AS year, e.source_text AS source
    ORDER BY e.std_start_year ASC, e.seq_index ASC
    """
    print(f"🔍 [Tool: get_person_timeline] 查询人物: {name}")
    try:
        results = run_query(cypher, {"name": name})
        if not results:
            return f"未找到关于人物 '{name}' 的生平事件记录。"
        return truncate_tool_output(json.dumps(results, ensure_ascii=False))
    except Exception as e:
        return f"查询出错: {str(e)}"

@tool
def search_historical_text(keyword: str) -> str:
    """通过关键词模糊搜索相关的历史事件描述和史料原文。当需要查找某个特定事件（如 '赤壁之战'、'衣带诏'）或查找含有特定词汇的史料时使用。"""
    cypher = """
    MATCH (e:Event)
    WHERE e.title CONTAINS $keyword OR e.description CONTAINS $keyword OR e.source_text CONTAINS $keyword
    OPTIONAL MATCH (e)-[:HAPPENED_AT]->(l:Location)
    RETURN e.title AS title, e.description AS description, e.time_text AS time, e.std_start_year AS year, e.source_text AS source, l.name AS location
    LIMIT 15
    """
    print(f"🔍 [Tool: search_historical_text] 搜索关键词: {keyword}")
    try:
        results = run_query(cypher, {"keyword": keyword})
        if not results:
            return f"未找到包含关键词 '{keyword}' 的事件记录。"
        return truncate_tool_output(json.dumps(results, ensure_ascii=False))
    except Exception as e:
        return f"查询出错: {str(e)}"

# ---------------------------------------------------

def run_agent_loop(llm_with_tools, rewritten_q: str, history_text: str) -> list:
    """运行 Agent Tool-Calling 循环收集信息"""
    agent_messages = [
        SystemMessage(content=AGENT_SYSTEM_PROMPT),
        HumanMessage(content=f"历史对话与摘要：\n{history_text}\n\n当前查询任务：\n{rewritten_q}")
    ]
    
    observations = []
    max_steps = 3
    step = 0
    
    while step < max_steps:
        print(f"🤖 [Agent Step {step+1}] 正在决策...")
        try:
            response = llm_with_tools.invoke(agent_messages)
        except Exception as e:
            print(f"⚠️ Agent 决策过程发生异常: {str(e)}")
            break
            
        agent_messages.append(response)
        
        if not response.tool_calls:
            print("🤖 [Agent] 决定结束信息收集。")
            break
            
        print(f"🤖 [Agent] 决定调用工具: {[tc['name'] for tc in response.tool_calls]}")
        
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_id = tool_call["id"]
            
            obs_str = ""
            try:
                if tool_name == "query_neo4j":
                    obs_str = query_neo4j.invoke(tool_args)
                elif tool_name == "get_person_timeline":
                    obs_str = get_person_timeline.invoke(tool_args)
                elif tool_name == "search_historical_text":
                    obs_str = search_historical_text.invoke(tool_args)
                else:
                    obs_str = f"Error: Tool '{tool_name}' not found."
            except Exception as e:
                obs_str = f"Error executing tool '{tool_name}': {str(e)}"
                
            print(f"📊 [Tool Observation] 收集到数据长度: {len(obs_str)}")
            
            observations.append({
                "tool": tool_name,
                "query": tool_args,
                "result": obs_str
            })
            
            agent_messages.append(ToolMessage(content=obs_str, tool_call_id=tool_id))
            
        step += 1
        
    return observations

def ask_question(question: str, history: list[dict] = None) -> str:
    # 0. Check Semantic Cache
    cached_ans, similarity = lookup_cache(question)
    if cached_ans:
        print(f"⚡ [语义缓存] 命中缓存 (相似度: {similarity * 100:.1f}%)，直接返回历史回答。")
        return cached_ans

    handler = AgentObservabilityCallbackHandler()
    token = active_callback_var.set(handler)
    
    llm_cheap = get_llm("cheap")
    llm_complex = get_llm("complex")
    
    answer = ""
    try:
        # 0. 对话历史解析与记忆压缩 (Memory summary)
        history_to_process = []
        if history:
            for msg in history:
                role = msg.get("role")
                content = msg.get("content")
                if role in ("user", "ai", "assistant") and content:
                    history_to_process.append((role, content))
            
            # 避免重复算入当前问题
            if history_to_process and history_to_process[-1][0] == "user" and history_to_process[-1][1] == question:
                history_to_process.pop()
                
            history_to_process = history_to_process[-20:]

        history_summary = ""
        recent_messages = history_to_process
        
        if len(history_to_process) > 6:
            # 进行记忆压缩，将前部分压缩为摘要，后 4 条完整保留
            older_messages = history_to_process[:-4]
            recent_messages = history_to_process[-4:]
            
            older_text = "\n".join([f"{'用户' if r == 'user' else 'AI'}: {c}" for r, c in older_messages])
            summary_prompt = MEM_SUMMARY_PROMPT.format(history_text=older_text)
            try:
                history_summary = llm_cheap.invoke([HumanMessage(content=summary_prompt)]).content.strip()
                print(f"📝 对话历史已自动压缩总结: '{history_summary}'")
            except Exception as e:
                print(f"⚠️ 对话历史压缩失败: {str(e)}")
                history_summary = ""
                recent_messages = history_to_process # 降级不压缩
                
        if history_summary:
            history_text = f"=== 历史对话摘要 ===\n{history_summary}\n\n"
        else:
            history_text = ""
            
        history_text += "\n".join([f"{'用户' if r == 'user' else 'AI'}: {c}" for r, c in recent_messages])
        if not history_text:
            history_text = "（无历史对话）"

        # 1. 意图拆解与问题重写
        print("🧠 正在拆解问题与分析意图...")
        analysis = None
        try:
            structured_llm = llm_cheap.with_structured_output(IntentAnalysis, method="function_calling")
            analysis_messages = [
                SystemMessage(content=INTENT_ANALYSIS_SYSTEM),
                HumanMessage(content=INTENT_ANALYSIS_PROMPT.format(history_text=history_text, question=question))
            ]
            analysis = structured_llm.invoke(analysis_messages)
        except Exception as e:
            print(f"⚠️ 意图拆解 structured_output 失败: {str(e)}，尝试原生 JSON 兜底。")
            try:
                fallback_prompt = INTENT_ANALYSIS_PROMPT.format(history_text=history_text, question=question) + "\n请返回一个符合上述 JSON schema 的对象（确保不要用 markdown 代码块标记，只输出 JSON 文本）。"
                res = llm_cheap.invoke([
                    SystemMessage(content=INTENT_ANALYSIS_SYSTEM + " You must output raw JSON only."),
                    HumanMessage(content=fallback_prompt)
                ]).content.strip()
                
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
                print(f"⚠️ 兜底 JSON 解析也失败: {str(e2)}，执行规则降级策略。")
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
                
        print(f"📋 意图拆解结果: 类型={analysis.type}, 重写问题='{analysis.rewritten_question}', 实体={analysis.entities}")

        q_type = analysis.type
        rewritten_q = analysis.rewritten_question
        
        # 1.5 验证提及的历史人物是否在图数据库中
        if q_type != "generic_chat" and getattr(analysis, "historical_characters", None):
            missing_chars = [name for name, exists in check_characters_exist(analysis.historical_characters).items() if not exists]
            if missing_chars:
                missing_str = "、".join(missing_chars)
                print(f"⚠️ 发现人物不在三国志中: {missing_str}")
                answer = f"抱歉，正史《三国志》中并未记载有关“{missing_str}”的任何信息。此人或非三国时期人物，或在《三国志》中无传无载，老夫无从考证。"
                save_cache(question, answer)
                return answer
        
        # 2a. 闲聊 / 会话历史查询
        if q_type == "generic_chat":
            print("💬 闲聊或会话历史查询，直接使用大模型回答...")
            chat_messages = [SystemMessage(content=f"{SYSTEM_PERSONA}请根据用户的当前问题和对话历史进行回答。")]
            for role, content in history_to_process:
                if role == "user":
                    chat_messages.append(HumanMessage(content=content))
                else:
                    chat_messages.append(AIMessage(content=content))
            chat_messages.append(HumanMessage(content=question))
            answer = llm_cheap.invoke(chat_messages).content
            save_cache(question, answer)
            return answer

        tools = [query_neo4j, get_person_timeline, search_historical_text]
        llm_with_tools = llm_complex.bind_tools(tools)
        all_observations = []

        # 2b. 复杂计划型查询拆解 (Plan-and-Solve)
        if q_type == "complex_planning":
            print("📋 复杂提问，启动计划拆解...")
            planning_prompt_formatted = PLANNING_PROMPT.format(question=rewritten_q)
            sub_queries = []
            try:
                plan_res = llm_complex.invoke([
                    SystemMessage(content="You are a planning assistant. Output JSON only matching the schema."),
                    HumanMessage(content=planning_prompt_formatted)
                ]).content.strip()
                
                if plan_res.startswith("```json"):
                    plan_res = plan_res[7:]
                elif plan_res.startswith("```"):
                    plan_res = plan_res[3:]
                if plan_res.endswith("```"):
                    plan_res = plan_res[:-3]
                    
                plan_res = plan_res.strip()
                sub_queries = json.loads(plan_res).get("sub_queries", [])
            except Exception as e:
                print(f"⚠️ 计划拆解失败: {str(e)}，降级为单一问题。")
                sub_queries = [rewritten_q]
                
            print(f"📋 拆解得到子问题群: {sub_queries}")
            
            for idx, sq in enumerate(sub_queries):
                print(f"➡️ 正在处理子问题 {idx+1}/{len(sub_queries)}: '{sq}'")
                sq_obs = run_agent_loop(llm_with_tools, sq, history_text)
                all_observations.extend(sq_obs)
                
        # 2c. 常规事实或关系查询
        else:
            all_observations = run_agent_loop(llm_with_tools, rewritten_q, history_text)

        # 2.5 检查是否检索到任何有效的数据库记录
        if not has_valid_db_records(all_observations):
            print("⚠️ 未检索到任何有效的 Neo4j 数据库记录，直接拒绝回答。")
            answer = "抱歉，在正史《三国志》及相关史料库中未搜寻到任何与该问题相关的史实记录，老夫无从考证。"
            save_cache(question, answer)
            return answer

        # 3. 汇总数据与自检故障
        print("✍️ 正在总结回答...")
        formatted_data = []
        query_failed = False
        last_error = None
        
        for obs in all_observations:
            res_data = obs["result"]
            if "Error executing Cypher query after retries" in res_data or "Database query failed permanently" in res_data:
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
            if query_failed:
                err_msg = last_error
            else:
                err_msg = "未触发任何工具调用或未检索到可用史实"
            answer_prompt += f"\n\n【注意】由于当前“简牍翻阅多有不便”（底盘检索阻碍：{err_msg}），藏书阁中暂未寻得详尽佐证。请基于你自身强大的《三国志》真实正史知识，直接对用户问题做出详实解答，并合理进行学者推演（回答中需隐晦体现因古籍翻阅不便而自行考证，严禁透露任何技术故障词汇）。"

        answer_messages = [SystemMessage(content=SYSTEM_PERSONA)]
        for role, content in history_to_process:
            if role == "user":
                answer_messages.append(HumanMessage(content=content))
            else:
                answer_messages.append(AIMessage(content=content))
        answer_messages.append(HumanMessage(content=answer_prompt))
        
        try:
            answer = llm_complex.invoke(answer_messages).content
            save_cache(question, answer)
        except Exception as e:
            answer = f"（老夫近日因病体抱恙，实在无力翻检书箧。望阁下稍候再问。）"
            
    finally:
        handler.finalize_run(question, answer)
        active_callback_var.reset(token)
        
    return answer

# ----------------- Async Streaming Version (Phase 3) -----------------

async def ask_question_stream(question: str, history: list[dict] = None) -> AsyncGenerator[str, None]:
    """
    异步流式发生器：使用 asyncio.Queue 在生产者线程与消费者生成器之间通信，
    支持实时上报思索轨迹（status）与打字机文本（text）。
    """
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

    async def run_query_async(cypher: str, params: dict = None) -> list[dict]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, run_query, cypher, params)

    async def check_characters_exist_async(names: List[str]) -> dict[str, bool]:
        if not names:
            return {}
        cypher = "UNWIND $names AS name OPTIONAL MATCH (p:Person {name: name}) RETURN name, p IS NOT NULL AS exists"
        try:
            results = await run_query_async(cypher, {"names": names})
            return {r["name"]: r["exists"] for r in results}
        except Exception as e:
            await send_event("status", f"⚠️ [检查人物] 数据库查询失败 ({str(e)})")
            return {name: True for name in names}

    # 动态声明异步 Agent 工具函数
    @tool
    async def query_neo4j_async(cypher: str) -> str:
        """执行 Neo4j Cypher 语句查询图数据库。当你需要复杂的图关系、多度查询或高度定制化的匹配时使用。"""
        max_retries = 2
        retry_count = 0
        last_error = None
        current_cypher = cypher
        
        execution_messages = [
            SystemMessage(content=SYSTEM_PERSONA),
            SystemMessage(content=GRAPH_SCHEMA),
            HumanMessage(content=f"请生成或执行以下查询所需的最合理的 Cypher：\n{cypher}")
        ]
        
        while retry_count <= max_retries:
            if retry_count > 0:
                await send_event("status", f"🔄 [query_neo4j] 正在尝试第 {retry_count} 次自修正 Cypher...")
                correction_prompt = f"""
上一次执行生成的 Cypher 语句时数据库报错了。
【错误信息】：
{last_error}
【当时生成的 Cypher】：
{current_cypher}
请仔细对照 Schema 修正语法或逻辑错误。请直接输出修正后的 Cypher 查询语句，不要有任何其他解释，不要用 markdown 代码块标记，直接输出纯文本。
"""
                execution_messages.append(AIMessage(content=current_cypher))
                execution_messages.append(HumanMessage(content=correction_prompt))
                res = await llm_complex.ainvoke(execution_messages)
                current_cypher = res.content.strip()
                
                if current_cypher.startswith("```cypher"):
                    current_cypher = current_cypher[9:]
                elif current_cypher.startswith("```"):
                    current_cypher = current_cypher[3:]
                if current_cypher.endswith("```"):
                    current_cypher = current_cypher[:-3]
                current_cypher = current_cypher.strip()

            await send_event("status", f"🔍 [query_neo4j] [第 {retry_count + 1} 次尝试] 执行 Cypher 检索...")
            try:
                results = await run_query_async(current_cypher)
                return truncate_tool_output(json.dumps(results, ensure_ascii=False))
            except Exception as e:
                last_error = str(e)
                await send_event("status", f"⚠️ [query_neo4j] 第 {retry_count + 1} 次检索失败: {last_error}")
                retry_count += 1
                
        return f"Database query failed permanently: {last_error}"

    @tool
    async def get_person_timeline_async(name: str) -> str:
        """获取特定三国历史人物的生平事件时间线。参数 name 是历史人物的中文名（例如 '曹操', '刘备', '徐晃'）。"""
        await send_event("status", f"🔍 [get_person_timeline] 正在翻阅人物 '{name}' 的生平编年史...")
        cypher = """
        MATCH (p:Person {name: $name})-[:PARTICIPATED_IN]->(e:Event)
        RETURN e.title AS title, e.description AS description, e.time_text AS time, e.std_start_year AS year, e.source_text AS source
        ORDER BY e.std_start_year ASC, e.seq_index ASC
        """
        try:
            results = await run_query_async(cypher, {"name": name})
            if not results:
                return f"未找到关于人物 '{name}' 的生平事件记录。"
            return truncate_tool_output(json.dumps(results, ensure_ascii=False))
        except Exception as e:
            return f"查询出错: {str(e)}"

    @tool
    async def search_historical_text_async(keyword: str) -> str:
        """通过关键词模糊搜索相关的历史事件描述和史料原文。当需要查找某个特定事件（如 '赤壁之战'）或含有特定词汇的史料时使用。"""
        await send_event("status", f"🔍 [search_historical_text] 正在全文库检索关键词 '{keyword}'...")
        cypher = """
        MATCH (e:Event)
        WHERE e.title CONTAINS $keyword OR e.description CONTAINS $keyword OR e.source_text CONTAINS $keyword
        OPTIONAL MATCH (e)-[:HAPPENED_AT]->(l:Location)
        RETURN e.title AS title, e.description AS description, e.time_text AS time, e.std_start_year AS year, e.source_text AS source, l.name AS location
        LIMIT 15
        """
        try:
            results = await run_query_async(cypher, {"keyword": keyword})
            if not results:
                return f"未找到包含关键词 '{keyword}' 的事件记录。"
            return truncate_tool_output(json.dumps(results, ensure_ascii=False))
        except Exception as e:
            return f"查询出错: {str(e)}"

    async def run_agent_loop_async(llm_with_tools, rewritten_q: str, history_text: str) -> list:
        agent_messages = [
            SystemMessage(content=AGENT_SYSTEM_PROMPT),
            HumanMessage(content=f"历史对话与摘要：\n{history_text}\n\n当前查询任务：\n{rewritten_q}")
        ]
        observations = []
        max_steps = 3
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
                        obs_str = await query_neo4j_async.ainvoke(tool_args)
                    elif tool_name == "get_person_timeline_async":
                        obs_str = await get_person_timeline_async.ainvoke(tool_args)
                    elif tool_name == "search_historical_text_async":
                        obs_str = await search_historical_text_async.ainvoke(tool_args)
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

            tools_async = [query_neo4j_async, get_person_timeline_async, search_historical_text_async]
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
            handler.finalize_run(question, ans_str)
            active_callback_var.reset(token)
            save_cache(question, ans_str)
            print("\n")

    producer_task = asyncio.create_task(producer())

    while True:
        event = await queue.get()
        if event is None:
            break
        yield json.dumps(event, ensure_ascii=False) + "\n"

if __name__ == "__main__":
    async def run_main():
        async for chunk in ask_question_stream("分析曹操在官渡之战前后的战略调整"):
            print(chunk.strip())
            
    asyncio.run(run_main())
