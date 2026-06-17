import os
import json
import glob
import asyncio
import re
from pathlib import Path
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Union
from langchain_openai import ChatOpenAI
from tqdm.asyncio import tqdm
from dotenv import load_dotenv

load_dotenv()

api_key = os.environ.get("DEEPSEEK_API_KEY", "")
llm = ChatOpenAI(
    model="deepseek-chat", 
    api_key=api_key, 
    base_url="https://api.deepseek.com/v1",
    max_tokens=8192,
    temperature=0.1,
    model_kwargs={"response_format": {"type": "json_object"}}
)

def salvage_events(raw_content: str) -> List[dict]:
    events = []
    raw_content = raw_content.replace("```json", "").replace("```", "")
    matches = list(re.finditer(r'\{\s*"事件标题"', raw_content))
    for match in matches:
        start_idx = match.start()
        brace_count = 0
        end_idx = -1
        for idx in range(start_idx, len(raw_content)):
            char = raw_content[idx]
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    end_idx = idx
                    break
        if end_idx != -1:
            obj_str = raw_content[start_idx:end_idx+1]
            try:
                obj = json.loads(obj_str)
                events.append(obj)
            except Exception:
                try:
                    cleaned_str = re.sub(r',\s*\}', '}', obj_str)
                    obj = json.loads(cleaned_str)
                    events.append(obj)
                except Exception:
                    pass
    return events

class SanguoEvent(BaseModel):
    title: str = Field(..., alias="事件标题", description="事件的简短标题")
    time: str = Field(..., alias="时间", description="事件发生的时间描述")
    location: str = Field(..., alias="地点", description="事件发生的地点")
    characters: List[str] = Field(..., alias="相关人物", description="涉及的所有主要历史人物")
    original_text: str = Field(..., alias="原文", description="提取出的三国志文言文原文片段")
    translation: str = Field(..., alias="事件翻译", description="对应的现代白话文翻译")
    std_start_year: Optional[int] = Field(None, description="标准开始年份（公元纪年整型，如 192）。若原文无明确年份，请结合历史知识与上下文合理推测并给出一个具体的公元纪年；若确实无法推测，可以写 null。切忌盲目使用默认年份。")
    groups: List[str] = Field(..., alias="涉及的集团", description="涉及的政治集团或家族")
    major_events: List[str] = Field(..., alias="所属事件", description="所属的三国重大历史事件")
    geography: List[str] = Field(..., alias="地理信息", description="涉及的东汉十三州/郡县地理实体")
    is_main_biography: bool = Field(..., alias="是否本传", description="该事件是否直接属于当前人物传记主体的核心生平事迹（若是则为 true，若只是作为旁白/提及他人则为 false）")

    @field_validator('time', mode='before')
    @classmethod
    def clean_time(cls, v):
        if v is None or str(v).strip().lower() in ('none', 'null', ''):
            return "不详"
        if isinstance(v, (int, float)):
            return str(int(v))
        return str(v).strip()

    @field_validator('location', mode='before')
    @classmethod
    def clean_location(cls, v):
        if v is None or str(v).strip().lower() in ('none', 'null', ''):
            return "不详"
        if isinstance(v, (int, float)):
            return str(int(v))
        return str(v).strip()

class EventExtractionResult(BaseModel):
    events: List[SanguoEvent]

def load_context_data():
    context_str = ""
    groups_path = "data/sanguo_groups_clans.json"
    if os.path.exists(groups_path):
        with open(groups_path, "r", encoding="utf-8") as f:
            groups_data = json.load(f)
            group_items = []
            for category in groups_data.values():
                if isinstance(category, list):
                    for item in category:
                        if isinstance(item, dict) and "id" in item and "name" in item:
                            group_items.append(f"{item['id']}({item['name']})")
            context_str += f"[可用政治集团/家族 ID 列表（格式为 ID(名称)）]:\n{', '.join(group_items)}\n\n"
            
    events_path = "data/sanguo_events.json"
    if os.path.exists(events_path):
        with open(events_path, "r", encoding="utf-8") as f:
            events_data = json.load(f)
            events_list = events_data.get("events", [])
            event_items = []
            for e in events_list:
                if "id" in e and "title" in e:
                    event_items.append(f"{e['id']}({e['title']})")
            context_str += f"[重大历史事件 ID 列表（格式为 ID(名称)）]:\n{', '.join(event_items)}\n\n"
            
    admin_path = "data/eastern_han_admin.json"
    if os.path.exists(admin_path):
        with open(admin_path, "r", encoding="utf-8") as f:
            admin_data = json.load(f)
            geo_items = []
            provinces = admin_data.get("provinces", [])
            for prov in provinces:
                prov_id = prov.get("id")
                if prov_id:
                    geo_items.append(prov_id)
                for cmd in prov.get("commanderies", []):
                    cmd_id = cmd.get("id")
                    if cmd_id:
                        geo_items.append(cmd_id)
                    for county in cmd.get("counties", []):
                        county_id = county.get("id")
                        if county_id:
                            geo_items.append(county_id)
            context_str += f"[标准地理 ID 列表]:\n{', '.join(geo_items)}\n\n"
            
    return context_str

def deduplicate_events(events: List[dict]) -> List[dict]:
    for i, ev in enumerate(events):
        ev['_orig_idx'] = i
        
    unique_events = []
    seen = set()
    for ev in events:
        orig = re.sub(r'\s+', '', ev.get("原文", ""))
        if not orig:
            continue
        if orig not in seen:
            seen.add(orig)
            unique_events.append(ev)
            
    unique_events.sort(key=lambda x: x['_orig_idx'])
    for ev in unique_events:
        ev.pop('_orig_idx', None)
    return unique_events

def clean_json_quotes(raw_content: str) -> str:
    keys = ["事件标题", "时间", "地点", "原文", "事件翻译"]
    next_keys_pattern = r"(?:事件标题|时间|地点|相关人物|原文|事件翻译|std_start_year|涉及的集团|所属事件|地理信息|是否本传)"
    lookahead = r'(?=\s*,\s*"' + next_keys_pattern + r'"\s*:|\s*,\s*\}|\s*\})'
    
    cleaned = raw_content
    for key in keys:
        pattern = r'"' + re.escape(key) + r'"\s*:\s*"(.*?)"' + lookahead
        
        def replace_match(match):
            val = match.group(1)
            val_escaped = re.sub(r'(?<!\\)"', r'\"', val)
            return f'"{key}": "{val_escaped}"'
            
        cleaned = re.sub(pattern, replace_match, cleaned, flags=re.DOTALL)
    return cleaned

async def refine_missed_text_with_llm(missed_text: str, biography_owner: str, context_str: str) -> List[dict]:
    system_prompt = f"""
你是一位精通《三国志》的资深历史学家。我们从原文中检测到一段被遗漏的历史文言文片段。请将这段遗漏文言文转换为结构化的 JSON 事件数据。
你需要根据文本内容提取出一个或多个合理的历史事件。

传主是：{biography_owner}

要求：
1. 「事件标题」要根据内容总结一个合理的标题（例如：“刘巴人物背景”、“刘巴字号与籍贯”），绝对不能起名叫“补充遗漏文本”。
2. 请合理分析或推测事件的时间、地点、相关人物、涉及集团和地理信息。
3. 请使用与标准事件相同的 JSON 格式输出：
{{
  "events": [
    {{
      "事件标题": "事件的简短标题",
      "时间": "时间描述（如：建安十三年）",
      "地点": "地点描述（如：赤壁）",
      "相关人物": ["人物1", "人物2"],
      "原文": "对应的三国志文言文原文片段",
      "事件翻译": "对应的现代白话文翻译",
      "std_start_year": 开始年份(整型，若无明确时间，请结合历史背景与上下文合理推测一个公元纪年；如确实无法确定则写 null),
      "涉及的集团": ["集团 ID（参考上表，如 'ying_chuan_xun'）"],
      "所属事件": ["大事件 ID（参考上表，如 'huang_jin_qi_yi'）"],
      "地理信息": ["标准地理ID，如'交州:郁林郡:右江'，优先定位到县，若不行则郡，再不行则州（必须匹配参考表）"],
      "是否本传": true 或者 false
    }}
  ]
}}
请参考以下字典映射补充字段：
{context_str}
"""
    try:
        user_prompt = f"[遗漏的文本]\n{missed_text}"
        messages = [
            ("system", system_prompt),
            ("user", user_prompt)
        ]
        response = await llm.ainvoke(messages)
        content = response.content
        content = clean_json_quotes(content)
        parsed_result = EventExtractionResult.model_validate_json(content)
        if parsed_result and parsed_result.events:
            return [e.model_dump(by_alias=True) for e in parsed_result.events]
    except Exception as e:
        print(f"  ⚠️ 遗漏文本精细化提取失败 ({e})，将使用基本兜底方案。")
        
    return [{
        "事件标题": f"{biography_owner}背景介绍" if biography_owner else "补充遗漏文本",
        "时间": "不详",
        "地点": "不详",
        "相关人物": [biography_owner] if biography_owner else [],
        "原文": missed_text,
        "事件翻译": missed_text,
        "std_start_year": None,
        "涉及的集团": [],
        "所属事件": [],
        "地理信息": [],
        "是否本传": True if biography_owner else False
    }]

async def extract_events_from_text(text_chunk: str, biography_owner: str, context_str: str, history_context: str = "") -> List[dict]:
    system_prompt = f"""
你是一位精通《三国志》的资深历史学家。请从下面提供的古文原文中，提取出所有有价值的历史事件，并将其转换为结构化的 JSON 数据。

### 核心要求
1. **绝对完整性与文本无缝覆盖（Zero Leakage，最重要）**：
   - 你必须对待提取原文进行**无缝覆盖**。输入原文中的**每一个字**（包括正文、括号 `[]` 内的裴松之注、引用文献、背景介绍、过渡段落等）都必须归属于提取出的某个事件的「原文」字段中，绝对不能有任何漏掉的句子或段落。
   - 括号 `[...]` 内的注释内容也必须作为一个独立的背景/评论事件提取，或与它所补充的主干事件合并提取，严禁直接丢弃。
   - **如果段落只是纯粹的背景介绍、人物籍贯、外貌描写、或是文末的“评曰”史官评论等（例如“评曰：霍峻孤城不倾...”），也必须将其强制包装为一个事件（例如标题起名为“人物背景”、“早期背景”或“史官评论/历史评价”），绝不能忽略，也绝不能直接输出非JSON文本。**
2. **完整句段与上下文（Context Integrity）**：
   - 每个事件的「原文」字段必须由**完整、连续的句子或段落**组成，包含明确的历史事实和语境，严禁断章取义地只截取对话或动作那一句而丢弃前面的前置背景介绍句子。
3. **事件粒度**：以**一个自然段**（或裴注中一个完整引用的段落）为基本事件粒度。由于输入的[待提取原文]本身就是这一个自然段，因此**原则上整个输入应该且只应该提取为一个事件**，绝对不要拆分细化为多个碎小的事件。
   - 绝不要逐句拆分：若一个段落内的几句话共同描述同一个完整历史进程或事实（如同一战役的过程、一次对话交往），必须合并为一个事件，其「原文」字段应完整包含输入段落的全部文字，不得拆成多句话。
   - 只有当这一段落中明确包含了多个完全独立、不相关的重大历史事实时，才允许进行拆分。
   - 关键节点（出生、死亡、重要战役、重大任命、名言、史评等）如果在段落内部，必须随整个段落合并提取，其「原文」为这一整段，严禁为了提取关键节点而强行拆散段落。
4. **时间与地点推测**：如果原文没有明确时间（如年号、干支）或地点，请根据上下文和历史知识合理推测，直接写数字年份（如 194）和地名，不要加任何“推测”标记。
5. **JSON 格式严格**：原文中出现的双引号（“ ”）和单引号（‘ ’）全部删除，确保生成的 JSON 可以被 `json.loads()` 正确解析。
6. **事件标题**：统一采用“谁 + 做了什么”的简洁事实描述，不加结果或影响。例如：“曹操在官渡击败袁绍”（正确），“曹操在官渡击败袁绍，奠定北方霸业基础”（错误）。
7. **事件翻译**：用现代白话文详细翻译对应的文言文原文片段，同样只陈述事实，不加评价或影响。
8. **相关人物**：必须包含本事件涉及的所有人物，包括主次角色，不得因人物“不重要”而省略。
9. **参考字典映射**：请参考以下列表，为每个事件补充 "涉及的集团", "所属事件", "地理信息" 这三个字段：

{context_str}

特别说明：
- **涉及的集团**：必须填写为上表提供的**集团 ID**（例如：`'ying_chuan_xun'`、`'he_nei_sima'`）。如果事件涉及某集团，则填入其 ID；可以填写多个。如果不涉及任何已知集团，则填写空列表 `[]`。
- **所属事件**：必须填写为上表提供的**重大事件 ID**（例如：`'huang_jin_qi_yi'`、`'guan_du_zhi_zhan'`）。如果该事件属于某个重大历史事件的分支或节点，则填入其 ID。如果不属于任何已知重大事件，则填写空列表 `[]`。
- **地理信息**：必须填写为上表提供的**标准行政区划 ID**（例如：`'交州:郁林郡:右江'`）。
- **细化定位原则**：请根据原文信息尽量细化地理定位，**如果能定位到具体的县，优先写县级 ID**（如 `'A:B:C'`）；如果只能定位到郡，写郡级 ID（如 `'A:B'`）；如果只能定位到州，写州级 ID（如 `'A'`）。必须使用列表中实际存在的 ID。
10. **严格区分输入区域（极重要）**：如果输入中包含“[背景上下文]”，它仅用于帮助你理解待提取原文中的代词、人物、时间或背景，你**绝对不能**从中提取任何事件。你必须且仅从“[待提取原文]”中提取事件。
11. **判定是否本传（is_main_biography，极重要）**：当前正在提取的传记主体（传主）是：**{biography_owner}**。对于每个事件，判定其是否为 **{biography_owner}** 本人的核心生平事迹：
    - 若该事件直接涉及 **{biography_owner}** 本人的核心生平、主要活动、主要言行、升迁或征战功绩，则该字段必须为 `true`。
    - 若该事件主要描述的是其他人的活动，而 **{biography_owner}** 仅作为旁白/背景提及或完全没有直接参与核心活动，则该字段 must 为 `false`。

### 输出 JSON 结构
必须输出为包含 "events" 数组 of JSON 对象，且各字段名如下：
{{
  "events": [
    {{
      "事件标题": "事件的简短标题",
      "时间": "时间描述（如：建安十三年）",
      "地点": "地点描述（如：赤壁）",
      "相关人物": ["人物1", "人物2"],
      "原文": "对应的三国志文言文原文片段",
      "事件翻译": "对应的现代白话文翻译",
      "std_start_year": 开始年份(整型，若无明确时间，请结合历史背景与上下文合理推测一个公元纪年；如确实无法确定则写 null，切忌盲目套用默认值),
      "涉及的集团": ["集团 ID（参考上表，如 'ying_chuan_xun'）"],
      "所属事件": ["大事件 ID（参考上表，如 'huang_jin_qi_yi'）"],
      "地理信息": ["标准地理ID，如'交州:郁林郡:右江'，优先定位到县，若不行则郡，再不行则州（必须匹配上表中的ID）"],
      "是否本传": true 或者 false
    }}
  ]
}}
"""

    events_to_return = []
    try:
        user_prompt = ""
        if history_context:
            user_prompt += f"[背景上下文（仅供参考，切勿从中提取任何事件）]\n{history_context}\n\n"
        user_prompt += f"[待提取原文（必须且仅从以下文本中提取所有事件）]\n{text_chunk}"

        messages = [
            ("system", system_prompt),
            ("user", user_prompt)
        ]
        
        response = await llm.ainvoke(messages)
        content = response.content
        content = clean_json_quotes(content)
        
        try:
            parsed_result = EventExtractionResult.model_validate_json(content)
            if parsed_result and parsed_result.events:
                events_to_return = [e.model_dump(by_alias=True) for e in parsed_result.events]
            else:
                # 如果是空列表，强制走抢救逻辑
                raise ValueError("解析成功但 events 列表为空")
        except Exception as e:
            print(f"  严格 JSON 校验失败: {e}。开始尝试抢救式局部解析...")
            print(f"  大模型原始输出: {content}")
            salvaged = salvage_events(content)
            valid_events = []
            for item in salvaged:
                try:
                    ev = SanguoEvent.model_validate(item)
                    valid_events.append(ev.model_dump(by_alias=True))
                except Exception as ve:
                    print(f"  └─ 单个事件校验失败 (已略过): {ve}，问题数据: {item.get('事件标题')}")
            
            if valid_events:
                print(f"  🎉 成功抢救出 {len(valid_events)} 个事件对象。")
                events_to_return = valid_events
            else:
                print(f"❌ 提取事件出错: 无法解析出任何有效的事件对象")
        
    except Exception as e:
        print(f"❌ 大模型调用或解析过程中出错: {e}")

    # 无论上面是成功解析、抢救成功，还是彻底失败，我们都在最后做一次绝对无缝覆盖检查
    extracted_text = "".join([ev.get("原文", "") for ev in events_to_return])
    ext_clean = re.sub(r'[^\u4e00-\u9fff]', '', extracted_text)
    
    # 优先匹配中括号内容 [...]；非括号内容则按 [。；？！] 或结尾切分，且确保在遭遇中括号时不丢失段前文字
    pattern = r'(\[[^\]]*\]|[^\[\]。；？！]+(?:[。；？！]|$|(?=\[)))'
    processed_sentences = [s.strip() for s in re.findall(pattern, text_chunk) if s.strip()]
        
    missed_text = ""
    for s in processed_sentences:
        s_clean = re.sub(r'[^\u4e00-\u9fff]', '', s)
        if not s_clean:
            continue
        if s_clean not in ext_clean:
            missed_text += s
            
    if missed_text:
        fallback_events = await refine_missed_text_with_llm(missed_text, biography_owner, context_str)
        events_to_return.extend(fallback_events)
        missed_len = len(re.sub(r'[^\u4e00-\u9fff]', '', missed_text))
        print(f"  ⚠️ 检测到 LLM 遗漏文本，已精细化提取找回 ({missed_len} 字)。")
        
    return events_to_return

async def process_file(file_path: str, context_str: str):
    file_name = os.path.basename(file_path)
    base_name = os.path.splitext(file_name)[0]
    out_path = f"data/raw/{base_name}_events.json"
    
    if os.path.exists(out_path):
        print(f"⏭️  跳过已处理文件: {file_name} (输出文件已存在: {out_path})")
        return
    
    # Extract biography owner from filename (e.g. "三国志_卷三十五 蜀书五 诸葛亮传第五" -> "诸葛亮")
    parts = base_name.split()
    biography_owner = parts[-1] if parts else "未知"
    biography_owner = re.sub(r'(?:传|纪)[一二三四五六七八九十百]+$', '', biography_owner)
    
    print(f"开始处理: {file_name} (传主: {biography_owner})")
    with open(file_path, "r", encoding="utf-8") as f:
        text = f.read()
        
    # 每次处理一个自然段
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    
    all_events = []
    prev_p = ""
    for i, p in enumerate(paragraphs):
        print(f"  正在提取 {file_name} 的第 {i+1}/{len(paragraphs)} 个自然段...")
        events = await extract_events_from_text(p, biography_owner, context_str, history_context=prev_p)
        all_events.extend(events)
        prev_p = p
        
    deduped_events = deduplicate_events(all_events)
        
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(deduped_events, f, ensure_ascii=False, indent=2)
        
    print(f"✅ 完成处理: {file_name}，共提取了 {len(deduped_events)} 个唯一事件。")

async def main(args):
    os.makedirs("data/raw", exist_ok=True)
    
    print("正在加载参考字典（集团、事件、地理）...")
    context_str = load_context_data()
    
    if args.file:
        if not os.path.exists(args.file):
            fallback_path = os.path.join("data/raw_book", args.file)
            if os.path.exists(fallback_path):
                raw_files = [fallback_path]
            else:
                print(f"❌ 指定的文件不存在: {args.file} (尝试路径: {fallback_path})")
                return
        else:
            raw_files = [args.file]
        print(f"🎯 仅处理指定的单个文件: {raw_files[0]}")
    else:
        raw_files = sorted(glob.glob("data/raw_book/*.md") + glob.glob("data/raw_book/*.txt"))
        print(f"找到 {len(raw_files)} 个原文文件待处理。")
    
    tasks = [process_file(f, context_str) for f in raw_files]
    await tqdm.gather(*tasks)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Extract events from Sanguozhi raw text using DeepSeek.")
    parser.add_argument(
        "--file", "-f", 
        type=str, 
        default=None, 
        help="Path or name of a specific txt file under data/raw_book/ to process."
    )
    args = parser.parse_args()
    
    asyncio.run(main(args))
