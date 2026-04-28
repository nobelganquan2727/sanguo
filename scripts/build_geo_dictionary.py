import os
import json
import glob
from tqdm import tqdm
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from typing import List, Optional

# 定义输出数据的单体结构
class GeoEntity(BaseModel):
    std_name: str = Field(description="标准化后的独立地名（如‘令支县’）")
    region: str = Field(description="汉末三国时期的州郡归属（如‘幽州-辽西郡’），如果不明填‘不详’")
    lat: Optional[float] = Field(description="现代 WGS84 维度的中心经度纬度。如果没有明确地点（如‘边塞’）填null")
    lng: Optional[float] = Field(description="现代 WGS84 维度的中心经度。如果没有明确地点填null")

class GeoMapping(BaseModel):
    original_str: str = Field(description="原始的‘地点’文本")
    entities: List[GeoEntity] = Field(description="拆解出来的标准地点实体列表（如果原句包含多个地点，拆成多个）")

class GeoDictResult(BaseModel):
    mappings: List[GeoMapping] = Field(description="映射结果列表")

def build_geo_dict():
    load_dotenv()
    llm = ChatOpenAI(
        model="deepseek-chat", 
        api_key=os.environ.get("DEEPSEEK_API_KEY"), 
        base_url="https://api.deepseek.com/v1",
        max_tokens=8192,
        temperature=0, 
        model_kwargs={"response_format": {"type": "json_object"}}
    )
    parser = JsonOutputParser(pydantic_object=GeoDictResult)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """你是一个中国古代历史地理学博士与GIS专家。
你在进行一项汉末三国时期实体消歧异（Entity Disambiguation）的任务。
我会给你一批从《三国志》事件里抽取的原始【地点】文本，它们非常脏。
可能会包含多个地点合写（如“许县、彭城”），也可能会有泛指（如“边塞”、“关东”）。

你需要做到：
1. 遇到含有多个地点的原文本，将其拆裂成多个独立的实体 (entities数组包含多个对象)。
2. 提供最标准的古地名 (std_name)。
3. 提供他们归属的州与郡 (region)。
4. 根据历史考证，推测出他们现代的经纬度 (lat, lng)。如果是泛指，经纬度给 null。

{format_instructions}"""),
        ("user", "请解析以下历史地点字符串（JSON数组格式）：\n{locations_json}")
    ])

    print("🔍 正在扫描所有人物 JSON 文件聚合全部独特地名...")
    raw_files = glob.glob("data/raw/*_events.json")
    unique_locations = set()

    for file_path in raw_files:
        with open(file_path, "r", encoding="utf-8") as f:
            events = json.load(f)
            for e in events:
                loc = e.get("地点")
                if loc and loc != "不详":
                    unique_locations.add(loc.strip())
                    
    locations_list = list(unique_locations)
    print(f"🌟 一共从几百本书里提取出了 {len(locations_list)} 个独一无二的地理空间字符串！")

    # 大模型一次最大输出Tokens约为8192，强制一波塞入一千个词会导致输出截断（JSON不完整）。
    # 因此内部将其分为每次 60 个词的小批次给LLM吞吐。
    BATCH_SIZE = 60
    master_geo_dict = {}
    chain = prompt | llm | parser

    output_file = "data/sanguo_geo_dictionary.json"
    
    # 支持断点续传，如果已经有的就不再测算
    if os.path.exists(output_file):
        with open(output_file, "r", encoding="utf-8") as f:
            master_geo_dict = json.load(f)
        print(f"📦 加载已有字典，包含 {len(master_geo_dict)} 个地点映射。")

    pending_locations = [loc for loc in locations_list if loc not in master_geo_dict]
    print(f"⏳ 剩余需要大模型推演的地点数量：{len(pending_locations)}")

    for i in tqdm(range(0, len(pending_locations), BATCH_SIZE)):
        batch = pending_locations[i:i+BATCH_SIZE]
        try:
            res = chain.invoke({
                "locations_json": json.dumps(batch, ensure_ascii=False),
                "format_instructions": parser.get_format_instructions()
            })
            
            for mapping in res.get("mappings", []):
                master_geo_dict[mapping["original_str"]] = mapping["entities"]
                
             # 查完一批就存一次盘，防止断网或者报错导致进度丢失
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(master_geo_dict, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            print(f"❌ 本批次提取失败: {e}")

    print(f"🎉 实体消歧完毕！主权地名字典已保存至: {output_file}")

if __name__ == "__main__":
    build_geo_dict()
