import json
import uuid

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
    t_short = set(short_text)
    t_long = set(long_text)
    if not t_short:
        return 0.0
    return len(t_short.intersection(t_long)) / len(t_short)

def extract_events_from_observations(observations: list, rewritten_q: str, final_ans: str) -> list[dict]:
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
            if not isinstance(parsed, list):
                parsed = [parsed]
                
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                # Check if it has a title
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
                
                # Filter by relevance threshold
                if relevance_score >= 0.15:
                    extracted.append((clean_event, relevance_score))
                    seen_titles.add(title)
        except Exception:
            pass
            
    # Sort events by relevance score descending
    extracted.sort(key=lambda x: x[1], reverse=True)
    return [x[0] for x in extracted]
