import os
import json
import asyncio
import requests
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

def truncate_tool_output(output: Any, max_chars: int = 12000, extra_warning: Optional[str] = None) -> str:
    """
    Safely truncates the tool output to avoid breaking JSON format
    when the output is too long.
    """
    suffix = f"\n\n【卷宗纪要说明】{extra_warning}" if extra_warning else ""
    
    if isinstance(output, str):
        try:
            parsed = json.loads(output)
            return truncate_tool_output(parsed, max_chars, extra_warning)
        except Exception:
            if len(output) > max_chars:
                return output[:max_chars] + f"\n\n【卷宗纪要说明】此处史料文字过长已作删减，仅展示前文{max_chars}字。" + suffix
            return output + suffix

    if isinstance(output, list):
        limit = max_chars - len(suffix)
        serialized = json.dumps(output, ensure_ascii=False)
        if len(serialized) <= limit:
            return serialized + suffix
            
        truncated = list(output)
        while len(truncated) > 1:
            truncated.pop()
            serialized = json.dumps(truncated, ensure_ascii=False)
            if len(serialized) <= limit:
                return serialized + f"\n\n【卷宗纪要说明】由于返回史料条数较多（共 {len(output)} 条，已截断，仅展示前 {len(truncated)} 条以防超出篇幅限制）。" + suffix
        
        if truncated:
            item = truncated[0]
            if isinstance(item, dict):
                item_copy = dict(item)
                for key in ["description", "translation", "source", "source_text"]:
                    if key in item_copy and isinstance(item_copy[key], str) and len(item_copy[key]) > 500:
                        item_copy[key] = item_copy[key][:500] + "...(此字段文本内容过长，已被强制截短)"
                truncated[0] = item_copy
                return json.dumps(truncated, ensure_ascii=False) + f"\n\n【卷宗纪要说明】单个史料文本内容过长，已强制截断内部文本以确保 JSON 格式完整。" + suffix
        return serialized + suffix

    if isinstance(output, dict):
        limit = max_chars - len(suffix)
        serialized = json.dumps(output, ensure_ascii=False)
        if len(serialized) <= limit:
            return serialized + suffix
        
        item_copy = dict(output)
        for key in ["description", "translation", "source", "source_text"]:
            if key in item_copy and isinstance(item_copy[key], str) and len(item_copy[key]) > 500:
                item_copy[key] = item_copy[key][:500] + "...(此字段文本内容过长，已被强制截短)"
        return json.dumps(item_copy, ensure_ascii=False) + f"\n\n【卷宗纪要说明】文本内容过长，已强制截断内部文本以确保 JSON 格式完整。" + suffix

    try:
        serialized = json.dumps(output, ensure_ascii=False)
        if len(serialized) > max_chars:
            return serialized[:max_chars] + f"\n\n【卷宗纪要说明】此处史料文字过长已作删减，仅展示前文{max_chars}字。" + suffix
        return serialized + suffix
    except Exception:
        s = str(output)
        if len(s) > max_chars:
            return s[:max_chars] + f"\n\n【卷宗纪要说明】此处史料文字过长已作删减，仅展示前文{max_chars}字。" + suffix
        return s + suffix

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
    """获取特定三国历史人物的生平事件时间线。参数 name 是历史人物的中文名。注意：曹操、刘备等大人物的事件极多，查询时必须传入 start_year 和 end_year 过滤到具体的时间段，以避免因返回过多记录而被截断或耗费巨大 Token。"""
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
    try:
        await emit_status(f"🔍 [get_person_timeline] 正在翻阅人物 '{name}' 的生平编年史{filter_desc}...")
        results = await run_query_async(cypher, params)
        if not results:
            return f"未找到关于人物 '{name}' 的生平事件记录。"
            
        is_condensed = False
        if start_year is None and end_year is None and len(results) > 10:
            is_condensed = True
            condensed_results = []
            for item in results:
                brief_item = {
                    "title": item.get("title"),
                    "time": item.get("time"),
                    "year": item.get("year"),
                    "locations": item.get("locations"),
                    "major_event": item.get("major_event")
                }
                condensed_results.append(brief_item)
            results = condensed_results
            
        has_more = False
        if len(results) > 30:
            results = results[:30]
            has_more = True
            
        warnings = []
        if is_condensed:
            warnings.append("由于未指定年份且生平事迹较多，已简写详细描述与原文。若需特定事件的详细史料，请在查询时指定 start_year 与 end_year 参数，或使用 search_vector_graph_async / search_historical_text_async 进行针对性检索。")
        if has_more:
            warnings.append("由于该人物生平记录较多，当前仅展示前 30 条事件。若想深究其他时间段的事迹，请传入 start_year 与 end_year 参数过滤查询。")
            
        extra_warning = "；".join(warnings) if warnings else None
        return truncate_tool_output(results, extra_warning=extra_warning)
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
    LIMIT 8
    """
    try:
        results = await run_query_async(cypher, {"keywords": keywords})
        if not results:
            return f"未找到包含关键词 '{keyword}' 的事件记录。"
        return truncate_tool_output(json.dumps(results, ensure_ascii=False))
    except Exception as e:
        return f"查询出错: {str(e)}"

async def get_bge_m3_embedding_async(text: str) -> list[float]:
    """Fetch BGE-M3 embedding from SiliconFlow API asynchronously."""
    api_key = os.environ.get("SILICONFLOW_API_KEY")
    if not api_key:
        raise ValueError("SILICONFLOW_API_KEY not found in environment!")
        
    url = "https://api.siliconflow.cn/v1/embeddings"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "BAAI/bge-m3",
        "input": text,
        "encoding_format": "float"
    }
    
    loop = asyncio.get_running_loop()
    def _post():
        res = requests.post(url, json=payload, headers=headers, timeout=15)
        res.raise_for_status()
        return res.json()["data"][0]["embedding"]
        
    return await loop.run_in_executor(None, _post)

@tool
async def search_vector_graph_async(query: str, k: Optional[int] = 5) -> str:
    """通过自然语言描述进行语义向量检索，查找与查询最相关的历史事件和史料原文。如果你需要查询特定历史大意/主题（如“曹操在官渡之战前的部署”），或用词难以精准匹配原文时，应首选此工具。"""
    await emit_status(f"🔍 [search_vector_graph] 正在语义向量检索: '{query}'...")
    try:
        embedding = await get_bge_m3_embedding_async(query)
    except Exception as e:
        await emit_status(f"⚠️ [search_vector_graph] 获取查询向量失败: {e}")
        return f"获取查询向量失败: {str(e)}"
        
    cypher = """
    CALL db.index.vector.queryNodes('eventEmbeddings', $k, $embedding)
    YIELD node, score
    MATCH (node:Event)
    OPTIONAL MATCH (node)-[:HAPPENED_AT]->(l:Location)
    OPTIONAL MATCH (node)-[:BELONGS_TO_MAJOR]->(me:MajorEvent)
    RETURN node.title AS title, COALESCE(node.translation, node.description) AS description, 
           node.time_text AS time, node.std_start_year AS year, node.source_text AS source, 
           collect(DISTINCT l.name) AS locations, me.title AS major_event, score
    ORDER BY score DESC
    """
    try:
        results = await run_query_async(cypher, {"k": k or 5, "embedding": embedding})
        if not results:
            return f"未找到与查询 '{query}' 相关的历史事件。"
        return truncate_tool_output(json.dumps(results, ensure_ascii=False))
    except Exception as e:
        return f"向量检索出错: {str(e)}"

