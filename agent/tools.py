import os
import json
import asyncio
from typing import Callable, Awaitable, Optional, Any
from contextvars import ContextVar
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.tools import tool

from agent.schema import GRAPH_SCHEMA
from agent.graph_client import run_query
from agent.prompts import SYSTEM_PERSONA
from agent.observability import active_callback_var

# --- ContextVar for streaming status events ---
active_send_event_var: ContextVar[Optional[Callable[[str, str], Awaitable[None]]]] = ContextVar("active_send_event", default=None)

async def emit_status(content: str):
    send_event = active_send_event_var.get()
    if send_event:
        await send_event("status", content)
    else:
        print(f"⚙️ [Agent Status] {content}")

# --- Helper Functions ---

def get_llm(model_type: str = "complex"):
    handler = active_callback_var.get()
    callbacks = [handler] if handler else []
    
    if model_type == "cheap":
        return ChatOpenAI(
            model="deepseek-v4-flash",
            api_key=os.environ.get("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com/v1",
            temperature=0,
            callbacks=callbacks,
            extra_body={"thinking": {"type": "disabled"}}
        )
    else:
        return ChatOpenAI(
            model="deepseek-chat", 
            api_key=os.environ.get("DEEPSEEK_API_KEY"), 
            base_url="https://api.deepseek.com/v1",
            max_tokens=8192,
            temperature=0,
            callbacks=callbacks,
            extra_body={"thinking": {"type": "disabled"}}
        )

def truncate_tool_output(output: Any, max_chars: int = 15000) -> str:
    """
    Safely truncates the tool output to avoid breaking JSON format
    when the output is too long.
    """
    if isinstance(output, str):
        try:
            # If it's a JSON string, parse it to do structured truncation
            parsed = json.loads(output)
            return truncate_tool_output(parsed, max_chars)
        except Exception:
            # Fallback string truncation
            if len(output) > max_chars:
                return output[:max_chars] + f"\n\n【卷宗纪要说明】此处史料文字过长已作删减，仅展示前文{max_chars}字。若仍需深究，请缩窄检索条件重新调阅。"
            return output

    # If it's a list, safely truncate by popping items
    if isinstance(output, list):
        serialized = json.dumps(output, ensure_ascii=False)
        if len(serialized) <= max_chars:
            return serialized
        
        truncated = list(output)
        while len(truncated) > 1:
            truncated.pop()
            serialized = json.dumps(truncated, ensure_ascii=False)
            if len(serialized) <= max_chars:
                return serialized + f"\n\n【卷宗纪要说明】由于返回史料条数较多（共 {len(output)} 条，已截断，仅展示前 {len(truncated)} 条以防超出篇幅限制）。"
        
        # If even 1 item is too long, truncate long string fields inside it
        if truncated:
            item = truncated[0]
            if isinstance(item, dict):
                item_copy = dict(item)
                for key, val in item_copy.items():
                    if isinstance(val, str) and len(val) > 2000:
                        item_copy[key] = val[:2000] + "...(此处略去过长文字)"
                truncated[0] = item_copy
                serialized = json.dumps(truncated, ensure_ascii=False)
                if len(serialized) <= max_chars:
                    return serialized + f"\n\n【卷宗纪要说明】单个史料文本内容过长，已作部分删减。"
                return serialized[:max_chars] + f"\n\n【卷宗纪要说明】此处史料文字过长已作删减，仅展示前文{max_chars}字。若仍需深究，请缩窄检索条件重新调阅。"

    # If it's a dict:
    if isinstance(output, dict):
        serialized = json.dumps(output, ensure_ascii=False)
        if len(serialized) <= max_chars:
            return serialized
        
        truncated_dict = dict(output)
        for key, val in truncated_dict.items():
            if isinstance(val, str) and len(val) > 2000:
                truncated_dict[key] = val[:2000] + "...(此处略去过长文字)"
        serialized = json.dumps(truncated_dict, ensure_ascii=False)
        if len(serialized) <= max_chars:
            return serialized + f"\n\n【卷宗纪要说明】史料文本内容过长，已作部分删减。"
        return serialized[:max_chars] + f"\n\n【卷宗纪要说明】此处史料文字过长已作删减，仅展示前文{max_chars}字。若仍需深究，请缩窄检索条件重新调阅。"

    try:
        serialized = json.dumps(output, ensure_ascii=False)
        if len(serialized) > max_chars:
            return serialized[:max_chars] + f"\n\n【卷宗纪要说明】此处史料文字过长已作删减，仅展示前文{max_chars}字。若仍需深究，请缩窄检索条件重新调阅。"
        return serialized
    except Exception:
        s = str(output)
        if len(s) > max_chars:
            return s[:max_chars] + f"\n\n【卷宗纪要说明】此处史料文字过长已作删减，仅展示前文{max_chars}字。若仍需深究，请缩窄检索条件重新调阅。"
        return s

async def run_query_async(cypher: str, params: dict = None) -> list[dict]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, run_query, cypher, params)

# ----------------- Tools Definition (Async) -----------------

@tool
async def query_neo4j_async(cypher: str) -> str:
    """执行 Neo4j Cypher 语句查询图数据库。当你需要复杂的图关系、多度查询或高度定制化的匹配时使用。"""
    llm_complex = get_llm("complex")
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
            await emit_status(f"🔄 [query_neo4j] 正在尝试第 {retry_count} 次自修正 Cypher...")
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

        await emit_status(f"🔍 [query_neo4j] [第 {retry_count + 1} 次尝试] 执行 Cypher 检索...")
        try:
            results = await run_query_async(current_cypher)
            return truncate_tool_output(json.dumps(results, ensure_ascii=False))
        except Exception as e:
            last_error = str(e)
            await emit_status(f"⚠️ [query_neo4j] 第 {retry_count + 1} 次检索失败: {last_error}")
            retry_count += 1
            
    return f"Database query failed permanently: {last_error}"

@tool
async def get_person_timeline_async(name: str, start_year: Optional[int] = None, end_year: Optional[int] = None) -> str:
    """获取特定三国历史人物的生平事件时间线。参数 name 是历史人物的中文名（例如 '曹操', '刘备'）。可传入可选参数 start_year 和 end_year 进行年份过滤以节省 Token。"""
    conditions = ["p.name = $name"]
    params = {"name": name}
    if start_year is not None:
        conditions.append("e.std_start_year >= $start_year")
        params["start_year"] = start_year
    if end_year is not None:
        conditions.append("e.std_start_year <= $end_year")
        params["end_year"] = end_year
    
    where_clause = " AND ".join(conditions)
    cypher = f"""
    MATCH (p:Person)-[:PARTICIPATED_IN]->(e:Event)
    WHERE {where_clause}
    OPTIONAL MATCH (e)-[:HAPPENED_AT]->(l:Location)
    OPTIONAL MATCH (e)-[:BELONGS_TO_MAJOR]->(me:MajorEvent)
    WITH e, collect(DISTINCT l.name) AS locations, me.title AS major_event
    ORDER BY e.std_start_year ASC, e.seq_index ASC
    RETURN e.title AS title, COALESCE(e.translation, e.description) AS description, e.time_text AS time, 
           e.std_start_year AS year, e.source_text AS source, locations, major_event
    """
    filter_desc = f" (时间范围: {start_year or ''} 至 {end_year or ''})" if (start_year or end_year) else ""
    await emit_status(f"🔍 [get_person_timeline] 正在翻阅人物 '{name}' 的生平编年史{filter_desc}...")
    try:
        results = await run_query_async(cypher, params)
        if not results:
            return f"未找到关于人物 '{name}' 的生平事件记录。"
        return truncate_tool_output(json.dumps(results, ensure_ascii=False))
    except Exception as e:
        return f"查询出错: {str(e)}"

@tool
async def search_historical_text_async(keyword: str) -> str:
    """通过关键词模糊搜索相关的历史事件描述和史料原文。当需要查找某个特定事件（如 '赤壁之战'）或含有特定词汇的史料时使用。"""
    raw_keywords = [k.strip() for k in keyword.split() if k.strip()]
    if not raw_keywords:
        return "关键词不能为空。"
    
    keywords = []
    for k in raw_keywords:
        if len(k) > 2:
            if k.endswith("之战"):
                k = k[:-2]
            elif k.endswith("战役"):
                k = k[:-2]
        keywords.append(k)
        
    await emit_status(f"🔍 [search_historical_text] 正在全文库检索关键词 {keywords}...")
    cypher = """
    MATCH (e:Event)
    WHERE ALL(k IN $keywords WHERE e.title CONTAINS k OR COALESCE(e.translation, e.description) CONTAINS k OR e.source_text CONTAINS k)
    OPTIONAL MATCH (e)-[:HAPPENED_AT]->(l:Location)
    OPTIONAL MATCH (e)-[:BELONGS_TO_MAJOR]->(me:MajorEvent)
    OPTIONAL MATCH (e)-[:INVOLVES_GROUP]->(g:Group)
    RETURN e.title AS title, COALESCE(e.translation, e.description) AS description, e.time_text AS time, 
           e.std_start_year AS year, e.source_text AS source, collect(DISTINCT l.name) AS locations, 
           me.title AS major_event, collect(DISTINCT g.name) AS groups
    LIMIT 15
    """
    try:
        results = await run_query_async(cypher, {"keywords": keywords})
        if not results:
            return f"未找到包含关键词 '{keyword}' 的事件记录。"
        return truncate_tool_output(json.dumps(results, ensure_ascii=False))
    except Exception as e:
        return f"查询出错: {str(e)}"
