import json
import uuid
import re
from typing import List, Any, Union, Optional, Callable
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from agent.schemas import DAGPlan, TaskSpec

def has_valid_db_records(observations: list, rewritten_q: Optional[str] = None) -> bool:
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
            # 兼容截断信息尾部的提示说明
            if "\n\n【卷宗纪要说明】" in res:
                res = res.split("\n\n【卷宗纪要说明】")[0]
            
            parsed = json.loads(res)
            if isinstance(parsed, list):
                if len(parsed) == 0:
                    continue
                # 必须包含实质性的史实内容（如标题、描述、译文、原文、地点，或者非空的事件列表）
                has_substance = False
                for item in parsed:
                    if not isinstance(item, dict):
                        has_substance = True
                        break
                    
                    # 清理 key 中的前缀（如 "p.name" 变为 "name"）
                    clean_keys = []
                    clean_item = {}
                    for k, v in item.items():
                        ck = k.split(".", 1)[1] if "." in k else k
                        clean_keys.append(ck)
                        clean_item[ck] = v

                    content_keys = ["title", "description", "translation", "source_text", "source", "events", "text", "location_name"]
                    if any(k in clean_keys for k in content_keys):
                        # 如果有 events 字段，确保它不能是空列表
                        if "events" in clean_item and isinstance(clean_item["events"], list) and len(clean_item["events"]) == 0:
                            continue
                        
                        # 若提供了 rewritten_q，则进行核心词相关性初筛，过滤纯路过的无关结果
                        if rewritten_q:
                            title = clean_item.get("title") or ""
                            desc = clean_item.get("description") or clean_item.get("desc") or clean_item.get("translation") or clean_item.get("source_text") or clean_item.get("source") or ""
                            query_words = re.findall(r"[\u4e00-\u9fa5]{2,}", rewritten_q)
                            if query_words:
                                match_found = False
                                for word in query_words:
                                    if word in ["怎样", "如何", "战略", "调整", "重大", "失误", "分析", "关系", "什么", "哪些", "前后"]:
                                        continue
                                    if word in title or word in desc:
                                        match_found = True
                                        break
                                if not match_found:
                                    continue # 核心词不匹配，跳过

                        has_substance = True
                        break
                    # 如果只包含人物基本属性（如姓名、势力），不视为有效的历史事件数据
                    non_content_keys = ["name", "alias", "faction", "id", "label"]
                    if not any(k not in non_content_keys for k in clean_keys):
                        continue
                    has_substance = True
                    break
                if not has_substance:
                    continue
        except Exception:
            pass
        return True
    return False

def get_similarity(s1: str, s2: str) -> float:
    if not s1 or not s2:
        return 0.0
    s1, s2 = s1.lower(), s2.lower()
    t1 = set(s1)
    t2 = set(s2)
    return len(t1.intersection(t2)) / len(t1.union(t2))

def get_containment_similarity(short_text: str, long_text: str) -> float:
    if not short_text or not long_text:
        return 0.0
    short_text, long_text = short_text.lower(), long_text.lower()
    if short_text in long_text:
        return 1.0
        
    def get_bigrams(text: str) -> set[str]:
        # 只保留汉字、字母和数字，过滤标点
        cleaned = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", text)
        return {cleaned[i:i+2] for i in range(len(cleaned) - 1)}

    bg_short = get_bigrams(short_text)
    bg_long = get_bigrams(long_text)
    
    if not bg_short:
        return 0.0
        
    return len(bg_short.intersection(bg_long)) / len(bg_short)

def extract_events_from_observations(observations: list, rewritten_q: str, final_ans: str, log_func: Optional[Callable[[str], None]] = None) -> list[dict]:
    def _find_events_recursively(data) -> list[dict]:
        results = []
        if isinstance(data, dict):
            title = data.get("title") or data.get("e.title")
            if title:
                results.append(data)
            for val in data.values():
                results.extend(_find_events_recursively(val))
        elif isinstance(data, list):
            for item in data:
                results.extend(_find_events_recursively(item))
        return results

    extracted = []
    seen_titles = set()
    for obs in observations:
        res_data = obs.get("result", "")
        if not res_data:
            continue
        try:
            # Remove any truncation trailer if present
            if "\n\n【卷宗纪要说明】" in res_data:
                res_data = res_data.split("\n\n【卷宗纪要说明】")[0]
            
            parsed = json.loads(res_data)
            event_items = _find_events_recursively(parsed)
                
            for item in event_items:
                title = item.get("title") or item.get("e.title")
                if not title:
                    continue
                if title in seen_titles:
                    continue
                    
                # Standardize location
                locations = item.get("locations") or item.get("location") or item.get("l.name")
                if not locations:
                    # Try to find location from any key ending with location or loc
                    for key, val in item.items():
                         if "location" in key.lower() or key.lower() == "loc":
                              locations = val
                              break
                              
                # Ensure locations is a list
                if locations:
                    if isinstance(locations, str):
                        locations = [locations]
                    elif isinstance(locations, dict):
                        locations = [locations]
                    elif not isinstance(locations, list):
                        locations = []
                else:
                    locations = []
                    
                # Standardize year
                year = item.get("year") or item.get("std_start_year") or item.get("e.std_start_year")
                if year is not None:
                    try:
                        year = int(year)
                    except (ValueError, TypeError):
                        year = None
                        
                # Standardize description/desc
                desc = item.get("description") or item.get("desc") or item.get("translation") or item.get("source_text") or item.get("source") or ""
                
                major_ev = item.get("major_event") or item.get("me.title")
                major_evs = item.get("major_events")
                if not major_evs and major_ev:
                    major_evs = [major_ev]
                if not major_evs:
                    major_evs = []
                
                # We construct a clean event dict for the map
                clean_event = {
                    "id": item.get("id") or item.get("e.id") or str(uuid.uuid4())[:8],
                    "title": title,
                    "year": year,
                    "desc": desc,
                    "locations": locations,
                    "type": item.get("type") or item.get("e.type") or "历史记录",
                    "protagonist": item.get("protagonist") or item.get("p.name") or "",
                    "major_events": major_evs,
                    "major_event": major_ev or ""
                }
                
                # Compute relevance score: Jaccard overlap with question + containment in final answer
                ans_score = get_containment_similarity(title, final_ans)
                q_score = get_similarity(title, rewritten_q)
                relevance_score = ans_score * 0.7 + q_score * 0.3
                
                is_accepted = relevance_score >= 0.15
                if log_func:
                    log_func(f"事件: '{title}' | 答案相关度: {ans_score:.3f} | 问题相关度: {q_score:.3f} | 综合评分: {relevance_score:.3f} | 结果: {'✅ 接受' if is_accepted else '❌ 丢弃'}")
                
                # Filter by relevance threshold
                if is_accepted:
                    extracted.append((clean_event, relevance_score))
                    seen_titles.add(title)
        except Exception as e:
            if log_func:
                log_func(f"解析/提取单个事件出错: {str(e)}")
            
    # Sort events by relevance score descending
    extracted.sort(key=lambda x: x[1], reverse=True)
    return [x[0] for x in extracted]


def clean_ai_message_for_history(content: str) -> str:
    """
    清洗历史对话中的 AI 回复，过滤掉冗余的引用块（>）和代码块，截断字数，
    保留回答结论，避免对话历史累积时导致 Context 爆炸。
    """
    if not content:
        return ""
    # 1. 过滤 markdown 块引用 (如 > “...”)
    lines = content.split('\n')
    cleaned_lines = [line for line in lines if not line.strip().startswith('>')]
    cleaned_content = '\n'.join(cleaned_lines)
    
    # 2. 过滤 markdown 代码块 (如 ```...```)
    cleaned_content = re.sub(r'```.*?```', '', cleaned_content, flags=re.DOTALL)
    
    # 3. 合并并精简换行
    cleaned_content = re.sub(r'\n+', '\n', cleaned_content).strip()
    
    # 4. 限制长度，防止长篇论证被完整带入上下文
    if len(cleaned_content) > 300:
        cleaned_content = cleaned_content[:300] + "...(余下史料已省略)"
        
    return cleaned_content


def validate_dag_plan(plan: DAGPlan) -> List[str]:
    """
    对生成的 DAG 计划进行静态安全与拓扑合法性校验。
    返回错误信息列表。若无错误，返回空列表。
    """
    errors = []
    task_ids = {t.id for t in plan.tasks}
    
    # 1. 校验 ID 唯一性
    if len(task_ids) != len(plan.tasks):
        errors.append("存在重复的任务 ID (id)。")
        
    # 2. 校验依赖的合法性
    for t in plan.tasks:
        for dep in t.dependencies:
            if dep not in task_ids:
                errors.append(f"任务 {t.id} 依赖的前置任务 {dep} 不存在。")
            if dep == t.id:
                errors.append(f"任务 {t.id} 不能自依赖。")
                
    # 3. 拓扑成环检测 (Kahn 算法)
    in_degree = {t.id: 0 for t in plan.tasks}
    adj = {t.id: [] for t in plan.tasks}
    for t in plan.tasks:
        for dep in t.dependencies:
            if dep in adj:
                adj[dep].append(t.id)
                in_degree[t.id] += 1
                
    queue = [tid for tid, deg in in_degree.items() if deg == 0]
    visited_count = 0
    while queue:
        u = queue.pop(0)
        visited_count += 1
        for v in adj[u]:
            in_degree[v] -= 1
            if in_degree[v] == 0:
                queue.append(v)
                
    if visited_count != len(plan.tasks):
        errors.append("任务依赖关系中存在循环依赖（有向图成环）。")
        
    # 4. Cypher 只读性与安全审计
    for t in plan.tasks:
        if t.tool == "query_neo4j_async":
            args_dict = t.args if isinstance(t.args, dict) else (t.args.model_dump() if hasattr(t.args, "model_dump") else getattr(t.args, "__dict__", {}))
            cypher = args_dict.get("cypher") or ""
            if not cypher:
                continue
            cypher = cypher.upper()
            if any(kw in cypher for kw in ["CREATE ", "MERGE ", "SET ", "DELETE ", "REMOVE ", "DETACH "]):
                errors.append(f"任务 {t.id} 的 Cypher 语句包含写操作，必须是只读查询。")
            # 校验允许的节点标签
            allowed_labels = ["PERSON", "EVENT", "LOCATION", "GROUP", "MAJOREVENT"]
            labels_found = re.findall(r"\(\s*(?:[a-zA-Z0-9_]+)?\s*:([a-zA-Z0-9_]+)", cypher)
            for lbl in labels_found:
                if lbl.upper() not in allowed_labels:
                    errors.append(f"任务 {t.id} 的 Cypher 语句包含未授权的节点标签: :{lbl}。仅允许: {allowed_labels}")
                    
    # 5. 校验占位符拼写与引用的合法性
    for t in plan.tasks:
        args_dict = t.args if isinstance(t.args, dict) else (t.args.model_dump() if hasattr(t.args, "model_dump") else (t.args.dict() if hasattr(t.args, "dict") else getattr(t.args, "__dict__", {})))
        for k, v in args_dict.items():
            if isinstance(v, str):
                placeholders = re.findall(r"\{\{([^}]+)\}\}", v)
                for ph in placeholders:
                    ph_parts = ph.strip().split(".")
                    dep_id = ph_parts[0]
                    if dep_id not in t.dependencies:
                        errors.append(f"任务 {t.id} 的参数 {k} 引用了未声明依赖的占位符 {ph}。")
                        
    return errors


def resolve_args_placeholders(args, raw_results):
    """
    递归遍历参数结构，解析并替换 {{task_id.output.property}} 占位符。
    支持基础数学运算，如 {{T1.output.year}} + 5
    """
    if isinstance(args, dict):
        return {k: resolve_args_placeholders(v, raw_results) for k, v in args.items()}
    if isinstance(args, list):
        return [resolve_args_placeholders(v, raw_results) for v in args]
    if isinstance(args, str):
        return evaluate_expression(args, raw_results)
    return args


def evaluate_expression(expr: str, raw_results: dict) -> Any:
    # 匹配 {{placeholder}} 语法
    pattern = r"\{\{([^}]+)\}\}"
    matches = re.findall(pattern, expr)
    if not matches:
        return expr
        
    resolved_expr = expr
    for m in matches:
        parts = m.strip().split(".")
        dep_id = parts[0]
        if dep_id not in raw_results:
            return expr # 依赖结果尚未就绪，直接返回原字符串
            
        val = raw_results[dep_id]
        resolved_val = None
        
        # 语法解析: id.output.property
        if len(parts) > 1 and parts[1] == "output":
            if len(parts) > 2:
                key = parts[2]
                if isinstance(val, list):
                    # 如果前置任务返回列表（如多个事件），提取第一个含有该属性的值
                    extracted = [item.get(key) for item in val if isinstance(item, dict) and key in item]
                    resolved_val = extracted[0] if extracted else None
                elif isinstance(val, dict):
                    resolved_val = val.get(key)
            else:
                resolved_val = val
        else:
            resolved_val = val
            
        if resolved_val is None:
            return expr
            
        # 用实际的数值替换占位符
        resolved_expr = resolved_expr.replace(f"{{{{{m}}}}}", str(resolved_val))
    
    # 支持简单安全的加减法运算，如 "211 + 5"，过滤非法字符防止安全隐患
    if re.match(r"^\d+\s*[\+\-]\s*\d+$", resolved_expr.strip()):
        try:
            return int(eval(resolved_expr))
        except Exception:
            return resolved_expr
            
    if resolved_expr.strip().isdigit():
        return int(resolved_expr.strip())
        
    return resolved_expr


def clean_obs_for_synthesis(obs_str: str) -> str:
    """
    用纯 Python 过滤数据库召回结果，仅保留原文和标题，丢弃冗余白话翻译和描述，防止合成端 Token 爆炸。
    """
    try:
        def _keep_synthesis_fields(data):
            if isinstance(data, dict):
                has_node_fields = any(k in data for k in ["description", "translation", "source_text", "source"])
                if has_node_fields:
                    keep_keys = ["title", "source", "source_text", "content", "name", "relationship", "chapter", "source_quote"]
                    return {k: _keep_synthesis_fields(v) for k, v in data.items() if k in keep_keys}
                else:
                    return {k: _keep_synthesis_fields(v) for k, v in data.items()}
            elif isinstance(data, list):
                return [_keep_synthesis_fields(item) for item in data]
            return data
        if "\n\n【卷宗纪要说明】" in obs_str:
            obs_str = obs_str.split("\n\n【卷宗纪要说明】")[0]
        parsed = json.loads(obs_str)
        return json.dumps(_keep_synthesis_fields(parsed), ensure_ascii=False)
    except Exception:
        return obs_str


def clean_obs_for_react(obs_str: str) -> str:
    """
    用纯 Python 过滤发给 ReAct 循环历史的消息，丢弃全部重型古文和翻译，仅保留标题和简述，防止 ReAct 步步累积 Token 爆炸。
    """
    try:
        def _keep_react_fields(data):
            if isinstance(data, dict):
                discard_keys = ["source_text", "source", "translation", "source_quote"]
                return {k: _keep_react_fields(v) for k, v in data.items() if k not in discard_keys}
            elif isinstance(data, list):
                return [_keep_react_fields(item) for item in data]
            return data
        parsed = json.loads(obs_str)
        return json.dumps(_keep_react_fields(parsed), ensure_ascii=False)
    except Exception:
        return obs_str


def consolidate_and_deduplicate_observations(all_observations: list) -> str:
    """
    汇编所有工具召回的观测事实并去重。通过标题 (title) 对事件节点去重，防止多个不同工具检索到完全相同的重复数据，彻底压缩合成层 Token 消耗。
    """
    unique_events = {}
    other_records = []
    
    for obs in all_observations:
        res_data = obs["result"]
        tool_name = obs["tool"]
        
        try:
            parsed = json.loads(res_data)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and "title" in item:
                        title = item["title"]
                        if title not in unique_events:
                            unique_events[title] = item
                        else:
                            existing = unique_events[title]
                            for k, v in item.items():
                                if v and (k not in existing or not existing[k]):
                                    existing[k] = v
                    else:
                        other_records.append(item)
            elif isinstance(parsed, dict):
                if "title" in parsed:
                    title = parsed["title"]
                    if title not in unique_events:
                        unique_events[title] = parsed
                else:
                    other_records.append(parsed)
            else:
                other_records.append(parsed)
        except Exception:
            other_records.append(res_data)
            
    consolidated = {}
    if unique_events:
        consolidated["events"] = list(unique_events.values())
    if other_records:
        consolidated["other_retrievals"] = other_records
        
    return json.dumps(consolidated, ensure_ascii=False, indent=2)
