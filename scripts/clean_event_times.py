import os
import json
import glob
import re
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from typing import List, Optional

# 定义标准化的时间结构
class TimePatch(BaseModel):
    original_text: str = Field(description="原始时间文本")
    start_year: Optional[int] = Field(description="标准的开始年份（公元），无法推算则填null")
    end_year: Optional[int] = Field(description="标准的结束年份（公元），若是单一点则与start_year相同")
    is_fuzzy: bool = Field(description="是否属于模糊时间（如‘某某年间’、‘某事件后’）")
    confidence: float = Field(description="推算置信度 0.0-1.0")

class TimePatchList(BaseModel):
    patches: List[TimePatch] = Field(description="对应的标准化时间补丁列表")

# 核心历史锚点字典 (作为上下文给到LLM，确保对齐)
HISTORICAL_ANCHORS = """
- 黄巾起义/中平元年: 184年
- 关东义兵起/讨伐董卓: 190年
- 董卓死/王允掌权: 192年
- 曹操迁都许县/建安元年: 196年
- 官渡之战: 200年
- 赤壁之战: 208年
- 魏文帝即位/黄初元年: 220年
- 夷陵之战: 222年
- 诸葛亮去世/五丈原: 234年
- 高平陵之变: 249年
- 蜀汉灭亡: 263年
- 三国归晋/吴灭亡: 280年
"""

def clean_times():
    load_dotenv()
    llm = ChatOpenAI(
        model="deepseek-chat", 
        api_key=os.environ.get("DEEPSEEK_API_KEY"), 
        base_url="https://api.deepseek.com/v1",
        max_tokens=8192,
        temperature=0, # 必须用0，保证逻辑一致性
        model_kwargs={"response_format": {"type": "json_object"}}
    )

    parser = JsonOutputParser(pydantic_object=TimePatchList)
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是一个精通中国古代历法与西历映射的历史专家。\n任务：将《三国志》中的描述性时间转化为公元纪年。\n参考锚点：\n" + HISTORICAL_ANCHORS + "\n\n{format_instructions}"),
        ("user", "对照以下原始时间描述，给出标准化的公元起始年份对：\n{time_list}")
    ])

    raw_files = glob.glob("data/raw/*_events.json")
    for file_path in raw_files:
        print(f"正在清洗文件: {file_path}")
        with open(file_path, "r", encoding="utf-8") as f:
            events = json.load(f)

        # 收集该文件中所有唯一的时间字符串
        unique_times = list(set(e.get("时间", "") for e in events if e.get("时间")))
        if not unique_times:
            continue

        try:
            # 调用LLM进行标准化
            chain = prompt | llm | parser
            res = chain.invoke({
                "time_list": json.dumps(unique_times, ensure_ascii=False),
                "format_instructions": parser.get_format_instructions()
            })
            
            # 建立映射表
            time_map = {p["original_text"]: p for p in res.get("patches", [])}

            # 应用补丁
            changed = False
            for e in events:
                raw_t = e.get("时间")
                if raw_t in time_map:
                    patch = time_map[raw_t]
                    e["std_start_year"] = patch.get("start_year")
                    e["std_end_year"] = patch.get("end_year")
                    e["is_time_fuzzy"] = patch.get("is_fuzzy")
                    changed = True
            
            if changed:
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(events, f, ensure_ascii=False, indent=2)
                print(f"✅ 完成清洗: {len(unique_times)} 个时间点对齐")

        except Exception as ex:
            print(f"❌ 清洗失败 {file_path}: {ex}")

if __name__ == "__main__":
    clean_times()
