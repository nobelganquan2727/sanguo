import os
import json
import asyncio
import requests
from typing import Callable, Awaitable, Optional, Any, List, Union
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

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

class ToolCallsFixerCallback(BaseCallbackHandler):
    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        flat_generations = [g for gens in response.generations for g in gens]
        for g in flat_generations:
            message = getattr(g, "message", None)
            tool_calls = getattr(message, "tool_calls", None)
            if not tool_calls or "tool_calls" in getattr(message, "additional_kwargs", {}):
                continue
            message.additional_kwargs["tool_calls"] = [
                {
                    "id": tc.get("id"),
                    "type": "function",
                    "function": {
                        "name": tc.get("name"),
                        "arguments": json.dumps(tc.get("args"), ensure_ascii=False)
                    }
                }
                for tc in tool_calls
            ]

def get_llm(model_type: str = "complex"):
    handler = active_callback_var.get()
    callbacks = [ToolCallsFixerCallback(), handler] if handler else []
    
    if model_type == "cheap":
        return ChatOpenAI(
            model="deepseek-v4-flash",
            api_key=os.environ.get("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com/v1",
            temperature=0,
            callbacks=callbacks,
            extra_body={"thinking": {"type": "disabled"}}
        ).with_config(run_name="DeepSeek-Cheap")
    elif model_type == "reasoner":
        return ChatOpenAI(
            model="deepseek-reasoner",
            api_key=os.environ.get("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com/v1",
            callbacks=callbacks,
        ).with_config(run_name="DeepSeek-Reasoner")
    else:
        return ChatOpenAI(
            model="deepseek-chat", 
            api_key=os.environ.get("DEEPSEEK_API_KEY"), 
            base_url="https://api.deepseek.com/v1",
            max_tokens=8192,
            temperature=0,
            callbacks=callbacks,
            extra_body={"thinking": {"type": "disabled"}}
        ).with_config(run_name="DeepSeek-Complex")

def truncate_tool_output(output: Any, max_chars: int = 12000, extra_warning: Optional[str] = None) -> str:
    """
    Safely truncates the tool output recursively to avoid breaking JSON format
    and prevent context/token bloat.
    """
    suffix = f"\n\n【卷宗纪要说明】{extra_warning}" if extra_warning else ""
    limit = max_chars - len(suffix)

    # 递归清理嵌套结构中的超长文本字段
    def _recursive_truncate(data: Any, max_val_len: int = 400) -> Any:
        if isinstance(data, dict):
            new_dict = {}
            for k, v in data.items():
                if k in ["description", "translation", "source", "source_text"] and isinstance(v, str) and len(v) > max_val_len:
                    new_dict[k] = v[:max_val_len] + "...(此字段文本内容过长，已被强制截短)"
                else:
                    new_dict[k] = _recursive_truncate(v, max_val_len)
            return new_dict
        elif isinstance(data, list):
            return [_recursive_truncate(item, max_val_len) for item in data]
        return data

    parsed = output
    if isinstance(output, str):
        try:
            clean_output = output
            if "\n\n【卷宗纪要说明】" in clean_output:
                clean_output = clean_output.split("\n\n【卷宗纪要说明】")[0]
            parsed = json.loads(clean_output)
        except Exception:
            if len(output) > limit:
                return output[:limit] + f"\n\n【卷宗纪要说明】此处史料文字过长已作删减，仅展示前文{limit}字。" + suffix
            return output + suffix

    # 递归截断长字段
    cleaned_parsed = _recursive_truncate(parsed)
    
    try:
        serialized = json.dumps(cleaned_parsed, ensure_ascii=False)
        if len(serialized) <= limit:
            return serialized + suffix
            
        # 如果整体序列化后依然超限，采用列表项截断
        if isinstance(cleaned_parsed, list):
            truncated = list(cleaned_parsed)
            while len(truncated) > 1:
                truncated.pop()
                serialized = json.dumps(truncated, ensure_ascii=False)
                if len(serialized) <= limit:
                    return serialized + f"\n\n【卷宗纪要说明】由于返回史料条数较多（共 {len(cleaned_parsed)} 条，已截断，仅展示前 {len(truncated)} 条以防超出篇幅限制）。" + suffix
            if truncated:
                return json.dumps(truncated, ensure_ascii=False) + f"\n\n【卷宗纪要说明】单条史料体积依然过大，已强制截短展示。" + suffix
        elif isinstance(cleaned_parsed, dict):
            s_dict = json.dumps(cleaned_parsed, ensure_ascii=False)
            return s_dict[:limit] + f"\n\n【卷宗纪要说明】检索数据文本量过大，已截取前文{limit}字。" + suffix
        return serialized[:limit] + suffix
    except Exception:
        s = str(output)
        if len(s) > limit:
            return s[:limit] + f"\n\n【卷宗纪要说明】数据文本过长已作删减，仅展示前文{limit}字。" + suffix
        return s + suffix

async def run_query_async(cypher: str, params: dict = None) -> list[dict]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, run_query, cypher, params)

# ----------------- Tools Definition (Async) -----------------

@tool
async def query_neo4j_async(question: Optional[str] = None, cypher: Optional[str] = None) -> str:
    """执行 Neo4j Cypher 语句查询图数据库。你可以传入自然语言子问题描述（在 question 参数中，推荐）或者直接传入 Cypher 语句（在 cypher 参数中）。"""
    import re
    llm_complex = get_llm("complex")
    
    # 1. 确定输入的查询意图
    query_input = ""
    is_direct_cypher = False
    
    if cypher:
        query_input = cypher
        is_direct_cypher = True
    elif question:
        query_input = question
        
    if not query_input:
        return "Error: No query question or Cypher provided."
        
    current_cypher = ""
    if is_direct_cypher:
        current_cypher = query_input
        
    max_retries = 2
    retry_count = 0
    last_error = None
    
    # 维护消息历史
    execution_messages = [
        SystemMessage(content=SYSTEM_PERSONA),
        SystemMessage(content=GRAPH_SCHEMA),
    ]
    
    if not is_direct_cypher:
        from agent.prompts import CYPHER_GENERATION_TEMPLATE, FEW_SHOT_EXAMPLES
        
        # 拼接 Few-shot 示例（静态 3 个典型示例，涵盖关系与单点事实查询）
        few_shots_str = ""
        for item in FEW_SHOT_EXAMPLES[:3]:
            few_shots_str += f"问题: {item['question']}\nCypher:\n{item['cypher']}\n\n"
            
        translation_prompt = CYPHER_GENERATION_TEMPLATE.format(
            schema=GRAPH_SCHEMA,
            few_shots=few_shots_str,
            question=query_input
        )
        execution_messages.append(HumanMessage(content=translation_prompt))
    else:
        execution_messages.append(HumanMessage(content=f"请执行以下 Cypher 查询，并确保它是安全且符合 Schema 的：\n{current_cypher}"))
        
    while retry_count <= max_retries:
        if retry_count > 0 or not current_cypher:
            if retry_count > 0:
                await emit_status(f"🔄 [query_neo4j] 正在尝试第 {retry_count} 次自修正 Cypher...")
                correction_prompt = f"""
上一次生成的 Cypher 语句在执行或校验时失败了。
【失败原因】：
{last_error}
【当时生成的 Cypher】：
{current_cypher}
请仔细对照 Schema 修正语法、逻辑错误或安全问题。请直接输出修正后的 Cypher 查询语句，不要有任何其他解释，不要用 markdown 代码块标记，直接输出纯文本。
"""
                execution_messages.append(AIMessage(content=current_cypher))
                execution_messages.append(HumanMessage(content=correction_prompt))
            else:
                await emit_status("🔍 [query_neo4j] 正在将自然语言子问题翻译为 Cypher...")
                
            res = await llm_complex.ainvoke(execution_messages)
            current_cypher = res.content.strip()
            
            # 清理 markdown 代码块
            if current_cypher.startswith("```cypher"):
                current_cypher = current_cypher[9:]
            elif current_cypher.startswith("```"):
                current_cypher = current_cypher[3:]
            if current_cypher.endswith("```"):
                current_cypher = current_cypher[:-3]
            current_cypher = current_cypher.strip()

        # 3. 动态安全审计与校验
        cypher_upper = current_cypher.upper()
        safety_error = None
        
        # A. 校验写操作
        if any(kw in cypher_upper for kw in ["CREATE ", "MERGE ", "SET ", "DELETE ", "REMOVE ", "DETACH "]):
            safety_error = "Cypher 语句包含写操作，必须是只读查询。"
            
        # B. 校验允许的节点标签
        if not safety_error:
            allowed_labels = ["PERSON", "EVENT", "LOCATION", "GROUP", "MAJOREVENT"]
            labels_found = re.findall(r"\(\s*(?:[a-zA-Z0-9_]+)?\s*:([a-zA-Z0-9_]+)", current_cypher)
            for lbl in labels_found:
                if lbl.upper() not in allowed_labels:
                    safety_error = f"Cypher 语句包含未授权的节点标签: :{lbl}。仅允许: {allowed_labels}"
                    break
                    
        if safety_error:
            last_error = f"安全/架构校验失败: {safety_error}"
            await emit_status(f"⚠️ [query_neo4j] 安全/架构校验未通过: {safety_error}")
            retry_count += 1
            current_cypher = ""  # 置空促使重新翻译/修正
            continue

        # 4. 执行 Cypher
        await emit_status(f"🔍 [query_neo4j] [第 {retry_count + 1} 次尝试] 执行 Cypher 检索: {current_cypher}")
        try:
            results = await run_query_async(current_cypher)
            return truncate_tool_output(json.dumps(results, ensure_ascii=False))
        except Exception as e:
            last_error = str(e)
            await emit_status(f"⚠️ [query_neo4j] 第 {retry_count + 1} 次检索失败: {last_error}")
            retry_count += 1
            
    return f"Database query failed permanently: {last_error}"


async def _get_single_person_timeline(name: str, start_year: Optional[int] = None, end_year: Optional[int] = None, query: Optional[str] = None) -> str:
    conditions = ["p.name = $name"]
    params = {"name": name}
    if start_year is not None:
        conditions.append("e.std_start_year >= $start_year")
        params["start_year"] = start_year
    if end_year is not None:
        conditions.append("e.std_start_year <= $end_year")
        params["end_year"] = end_year
    
    where_clause = " AND ".join(conditions)
    
    if query:
        # 如果提供了 query，执行语义向量过滤，找出该人物生平中与 query 最相关的 top 12 个事件
        try:
            embedding = await get_bge_m3_embedding_async(query)
            
            from agent.cache import get_event_embeddings_collection
            loop = asyncio.get_running_loop()
            def _query_chroma():
                collection = get_event_embeddings_collection()
                # 召回 100 条可能相关的事件以确保能在图数据库中匹配到该人
                return collection.query(
                    query_embeddings=[embedding],
                    n_results=100
                )
            chroma_res = await loop.run_in_executor(None, _query_chroma)
            
            if not chroma_res or not chroma_res.get("ids") or len(chroma_res["ids"][0]) == 0:
                return f"未找到关于人物 '{name}' 且与主题 '{query}' 相关的生平事件记录。"
                
            retrieved_ids = chroma_res["ids"][0]
            distances = chroma_res["distances"][0] if "distances" in chroma_res else [0.0] * len(retrieved_ids)
            scores_map = {eid: 1.0 - dist for eid, dist in zip(retrieved_ids, distances)}
            
            params["ids"] = retrieved_ids
            
            cypher = f"""
            MATCH (p:Person)-[:PARTICIPATED_IN]->(node:Event)
            WHERE {where_clause.replace("e.", "node.")} AND node.id IN $ids
            OPTIONAL MATCH (node)-[:HAPPENED_AT]->(l:Location)
            OPTIONAL MATCH (node)-[:BELONGS_TO_MAJOR]->(me:MajorEvent)
            WITH node, collect(DISTINCT l.name) AS locations, me.title AS major_event
            RETURN node.title AS title, COALESCE(node.translation, node.description) AS description, node.time_text AS time, 
                   node.std_start_year AS year, node.source_text AS source, locations, major_event, node.id AS id
            """
            await emit_status(f"🔍 [get_person_timeline] [Chroma分离版] 正在执行语义过滤编年史，筛选与主题 '{query}' 相关的事件...")
            results = await run_query_async(cypher, params)
            if not results:
                return f"未找到关于人物 '{name}' 且与主题 '{query}' 相关的生平事件记录。"
                
            # 还原相关性评分并降序排列，取 Top 12
            for r in results:
                r["score"] = scores_map.get(r["id"], 0.0)
            results.sort(key=lambda x: x.get("score", 0.0), reverse=True)
            results = results[:12]
            
            return truncate_tool_output(json.dumps(results, ensure_ascii=False))
        except Exception as e:
            await emit_status(f"⚠️ [get_person_timeline] 语义过滤失败，退回执行标准编年史检索。原因: {e}")
            pass

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
async def get_person_timeline_async(name: Union[str, List[str]], start_year: Optional[int] = None, end_year: Optional[int] = None, query: Optional[str] = None) -> str:
    """获取一个或多个三国历史人物的生平事件时间线。参数 name 可以是单个名字的字符串，或者是包含多个中文名字的列表。若需要针对特定主题（如 '初期实力'、'官渡之战'）进行过滤，可传入 query 参数进行语义向量筛选，避免返回过多无关 of 纪年事件。"""
    if isinstance(name, list):
        tasks = []
        for n in name:
            tasks.append(_get_single_person_timeline(n, start_year, end_year, query))
        results = await asyncio.gather(*tasks)
        return "\n---\n".join(results)
    else:
        return await _get_single_person_timeline(name, start_year, end_year, query)

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
        
    try:
        from agent.cache import get_event_embeddings_collection
        
        loop = asyncio.get_running_loop()
        def _query_chroma():
            collection = get_event_embeddings_collection()
            return collection.query(
                query_embeddings=[embedding],
                n_results=k or 5
            )
        chroma_res = await loop.run_in_executor(None, _query_chroma)
        
        if not chroma_res or not chroma_res.get("ids") or len(chroma_res["ids"][0]) == 0:
            return f"未找到与查询 '{query}' 相关的历史事件。"
            
        retrieved_ids = chroma_res["ids"][0]
        distances = chroma_res["distances"][0] if "distances" in chroma_res else [0.0] * len(retrieved_ids)
        scores_map = {eid: 1.0 - dist for eid, dist in zip(retrieved_ids, distances)}
        
    except Exception as e:
        await emit_status(f"⚠️ [search_vector_graph] ChromaDB 检索失败: {e}")
        return f"ChromaDB 检索失败: {str(e)}"

    cypher = """
    MATCH (node:Event)
    WHERE node.id IN $ids
    OPTIONAL MATCH (node)-[:HAPPENED_AT]->(l:Location)
    OPTIONAL MATCH (node)-[:BELONGS_TO_MAJOR]->(me:MajorEvent)
    RETURN node.title AS title, COALESCE(node.translation, node.description) AS description, 
           node.time_text AS time, node.std_start_year AS year, node.source_text AS source, 
           collect(DISTINCT l.name) AS locations, me.title AS major_event, node.id AS id
    """
    try:
        results = await run_query_async(cypher, {"ids": retrieved_ids})
        if not results:
            return f"未找到与查询 '{query}' 相关的历史事件。"
            
        # 还原打分并按相似度高低进行结果重排序，确保 Chroma 的检索顺序不被打乱
        for r in results:
            r["score"] = scores_map.get(r["id"], 0.0)
        results.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        
        return truncate_tool_output(json.dumps(results, ensure_ascii=False))
    except Exception as e:
        return f"图数据库数据拉取出错: {str(e)}"

