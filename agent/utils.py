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
                            # 使用 2 字符滑动窗口生成候选词，避免连续中文不分词导致匹配失效
                            query_words = []
                            for i in range(len(rewritten_q) - 1):
                                w = rewritten_q[i:i+2]
                                # 排除常见无意义词与虚词
                                if not any(x in w for x in ["怎样", "如何", "战略", "调整", "重大", "失误", "分析", "关系", "什么", "哪些", "前后", "在", "的", "之", "与", "及", "和", "或"]):
                                    query_words.append(w)
                            if query_words:
                                match_found = False
                                for word in query_words:
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


def clean_obs_for_react(obs_str: str, rewritten_q: Optional[str] = None, relevant_ids: Optional[set] = None) -> str:
    """
    用纯 Python 过滤发给 ReAct 循环历史的消息，丢弃全部重型古文和翻译，仅保留标题和简述，防止 ReAct 步步累积 Token 爆炸。
    如果列表长度大于 10 且提供了 rewritten_q，则优先通过全局语义过滤器或 bigram 候选词对事件进行核心相关性初筛。
    """
    try:
        if isinstance(obs_str, str):
            if "\n\n【卷宗纪要说明】" in obs_str:
                obs_str = obs_str.split("\n\n【卷宗纪要说明】")[0]
            parsed = json.loads(obs_str)
        else:
            parsed = obs_str
        def _keep_react_fields(data):
            if isinstance(data, dict):
                discard_keys = ["source_text", "source", "translation", "source_quote"]
                res = {}
                for k, v in data.items():
                    if k in discard_keys:
                        continue
                    if isinstance(v, str) and len(v) > 80:
                        res[k] = v[:80] + "..."
                    else:
                        res[k] = _keep_react_fields(v)
                return res
            elif isinstance(data, list):
                return [_keep_react_fields(item) for item in data]
            return data
        
        cleaned = _keep_react_fields(parsed)
        
        if isinstance(cleaned, list) and len(cleaned) > 10 and rewritten_q:
            filtered_list = []
            
            # 1. 优先使用全局语义过滤器进行过滤
            if relevant_ids:
                filtered_list = [item for item in cleaned if isinstance(item, dict) and item.get("id") in relevant_ids]
            
            # 2. 如果没有语义过滤器或过滤完为空，退化为 bigram 滑动匹配
            if not filtered_list:
                query_words = []
                for i in range(len(rewritten_q) - 1):
                    w = rewritten_q[i:i+2]
                    if not any(x in w for x in ["怎样", "如何", "战略", "调整", "重大", "失误", "分析", "关系", "什么", "哪些", "前后", "在", "的", "之", "与", "及", "和", "或"]):
                        query_words.append(w)
                
                if query_words:
                    for item in cleaned:
                        if not isinstance(item, dict):
                            filtered_list.append(item)
                            continue
                        
                        title = item.get("title") or ""
                        desc = item.get("description") or item.get("desc") or ""
                        
                        match_found = False
                        for word in query_words:
                            if word in title or word in desc:
                                match_found = True
                                break
                        if match_found:
                            filtered_list.append(item)
            
            # 防止过滤后为空，若不为空则替换
            if filtered_list:
                cleaned = filtered_list
                
        # 硬上限限制：在 ReAct 状态提取中，最多保留前 12 条记录以防单步骤 Token 爆炸
        if isinstance(cleaned, list) and len(cleaned) > 12:
            cleaned = cleaned[:12]
            
        return json.dumps(cleaned, ensure_ascii=False)
    except Exception:
        return obs_str


def consolidate_and_deduplicate_observations(
    all_observations: list, 
    rewritten_q: Optional[str] = None,
    historical_characters: Optional[list] = None,
    relevant_ids: Optional[set] = None
) -> str:
    """
    汇编所有工具召回的观测事实并去重。
    - 针对 timeline 工具（get_person_timeline_async, get_location_timeline_async）召回的事件，保留其原有的时间线先后顺序（不基于关键词相似度过滤，以防过滤掉未来的战略经历或战后连锁反应）。
    - 针对其他工具（如向量检索、Neo4j自定义查询），基于关键词匹配相似度排序并筛选。
    - 去重并通过硬上限防止 Token 爆炸。
    """
    timeline_events = {}
    other_events = {}
    other_records = []
    
    # 识别问题是否在问某人“之后”、“死后”的事件
    after_characters = []
    if rewritten_q and historical_characters:
        for char in historical_characters:
            if re.search(rf"{char}(?:之后|死后|逝世后|去世后|后)", rewritten_q):
                after_characters.append(char)
                
    for obs in all_observations:
        res_data = obs.get("raw_result") or obs.get("result", "")
        if not res_data:
            continue
        if isinstance(res_data, str):
            if "\n\n【卷宗纪要说明】" in res_data:
                res_data = res_data.split("\n\n【卷宗纪要说明】")[0]
        tool_name = obs.get("tool", "")
        
        try:
            parsed = json.loads(res_data)
            
            def process_item(item):
                if isinstance(item, dict) and "title" in item:
                    title = item["title"]
                    # 过滤“之后/死后”事件中涉及人物自身的无关记录
                    is_irrelevant = False
                    if after_characters:
                        for char in after_characters:
                            if char in title:
                                is_irrelevant = True
                                break
                    if is_irrelevant:
                        return
                        
                    # 根据来源工具分类
                    if tool_name in ["get_person_timeline", "get_location_timeline"]:
                        if title not in timeline_events:
                            timeline_events[title] = item
                        else:
                            existing = timeline_events[title]
                            for k, v in item.items():
                                if v and (k not in existing or not existing[k]):
                                    existing[k] = v
                    else:
                        if title not in other_events:
                            other_events[title] = item
                        else:
                            existing = other_events[title]
                            for k, v in item.items():
                                if v and (k not in existing or not existing[k]):
                                    existing[k] = v
                elif isinstance(item, dict):
                    # 检查是否嵌套了事件列表
                    nested_lists = [v for v in item.values() if isinstance(v, list)]
                    has_nested = False
                    for lst in nested_lists:
                        sub_events = [x for x in lst if isinstance(x, dict) and "title" in x]
                        if sub_events:
                            has_nested = True
                            for sub_item in sub_events:
                                process_item(sub_item)
                    if not has_nested:
                        other_records.append(item)
                else:
                    other_records.append(item)
                    
            if isinstance(parsed, list):
                for x in parsed:
                    process_item(x)
            elif isinstance(parsed, dict):
                process_item(parsed)
        except Exception:
            other_records.append(res_data)
            
    # 汇整并排序时间线事件（保持时间先后顺序）
    timeline_list = list(timeline_events.values())
    timeline_list.sort(key=lambda x: x.get("year") if x.get("year") is not None else -999)
    
    # 若时间线事件过多（> 15），则利用核心词对时间线事件进行相关性初筛，防 token 爆炸
    if len(timeline_list) > 15 and rewritten_q:
        filtered_timeline = []
        
        # 1. 优先使用全局语义过滤器进行过滤
        if relevant_ids:
            filtered_timeline = [item for item in timeline_list if item.get("id") in relevant_ids]
            
        # 2. 如果没有语义过滤器或过滤后为空，退化为 bigram 滑动匹配
        if not filtered_timeline:
            query_words = []
            for i in range(len(rewritten_q) - 1):
                w = rewritten_q[i:i+2]
                if not any(x in w for x in ["怎样", "如何", "战略", "调整", "重大", "失误", "分析", "关系", "什么", "哪些", "前后", "在", "的", "之", "与", "及", "和", "或"]):
                    query_words.append(w)
            if historical_characters:
                if len(historical_characters) == 1:
                    query_words = [w for w in query_words if not any(hc in w or w in hc for hc in historical_characters)]
                else:
                    query_words.extend(historical_characters)
                
            if query_words:
                for item in timeline_list:
                    title = item.get("title") or ""
                    desc = item.get("description") or item.get("translation") or item.get("source_text") or item.get("source") or ""
                    full_text = title + " " + desc
                    
                    match_found = False
                    for word in query_words:
                        if word in full_text:
                            match_found = True
                            break
                    if match_found:
                        filtered_timeline.append(item)
                        
        if filtered_timeline:
            timeline_list = filtered_timeline
    
    # 筛选其他事件（基于与 rewritten_q 的关键词重合度排序，防止大量非时间线数据膨胀）
    other_events_list = list(other_events.values())
    if rewritten_q and other_events_list:
        scored_events = []
        for item in other_events_list:
            title = item.get("title") or ""
            desc = item.get("description") or item.get("translation") or item.get("source_text") or item.get("source") or ""
            full_text = title + " " + desc
            score = get_containment_similarity(rewritten_q, full_text)
            scored_events.append((item, score))
        scored_events.sort(key=lambda x: x[1], reverse=True)
        # 其他事件只取最相关的前 6 个
        other_events_list = [x[0] for x in scored_events[:6]]
        
    # 合并：时间线事件放前，补充匹配事件放后
    events_list = timeline_list + other_events_list
    
    consolidated = {}
    if events_list:
        consolidated["events"] = events_list
    if other_records:
        consolidated["other_retrievals"] = other_records
        
    return json.dumps(consolidated, ensure_ascii=False, indent=2)
