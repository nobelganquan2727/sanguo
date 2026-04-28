import os
import json
import glob
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from typing import List, Optional

class GeoLocation(BaseModel):
    ancient_name: str = Field(description="古地名，原样返回")
    modern_name: Optional[str] = Field(description="推测的现代所在地名称，找不到填未知")
    lat: Optional[float] = Field(description="经纬度中北纬纬度数值，找不到填 null")
    lng: Optional[float] = Field(description="经纬度中东经经度数值，找不到填 null")

class GeoList(BaseModel):
    locations: List[GeoLocation] = Field(description="解析出的地理坐标列表")

def get_unique_locations(data_dir="data/raw"):
    locations = set()
    for file_path in glob.glob(os.path.join(data_dir, "*_events.json")):
        with open(file_path, "r", encoding="utf-8") as f:
            events = json.load(f)
            for event in events:
                loc_str = event.get("地点", "")
                if loc_str and "不详" not in loc_str:
                    # 按照顿号、逗号、斜杠分割
                    import re
                    parts = re.split(r'[、/，,]', loc_str)
                    for p in parts:
                        cleaned = p.strip()
                        if cleaned and len(cleaned) < 10:  # 排除异常长句子
                            locations.add(cleaned)
    return list(locations)

def run_geo_encoder():
    print("📍 正在扫描本地所有事件，提取去重后的全量古地名...")
    all_locs = get_unique_locations()
    print(f"共扫描到独立的古地名 {len(all_locs)} 个！")
    
    if not all_locs:
        print("当前没有任何数据，等待批处理完成再试吧！")
        return

    load_dotenv()
    llm = ChatOpenAI(
        model="deepseek-chat", 
        api_key=os.environ.get("DEEPSEEK_API_KEY"), 
        base_url="https://api.deepseek.com/v1",
        max_tokens=8192,
        temperature=0.1
    )

    parser = JsonOutputParser(pydantic_object=GeoList)
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是中国历史地理学博士，精通谭其骧《中国历史地图集》与三国时代行政区划。\n任务：我将给你一批三国时代的古地名，请在现代地球 WGS84 坐标系下，标出它们所对应的中心点精确坐标。\n要求：如果没有极度精确点，请给出其现代对应市/县/遗址的中心点。若完全无考则返回 null。\n\n{format_instructions}"),
        ("user", "以下是需要打点的三国古地名列表（批量获取）：\n{locations}")
    ])

    # 这里为了防止一次性送两百个导致模型断流或幻觉，其实应当分批（Batch），Demo 先一次性送50个
    batch_size = 50
    results = {}
    
    for i in range(0, len(all_locs), batch_size):
        batch_locs = all_locs[i:i+batch_size]
        print(f"\n🚀 正在发送第 {i+1} 到 {i+len(batch_locs)} 个地名给大模型查经纬度...")
        try:
            chain = prompt | llm | parser
            res = chain.invoke({
                "locations": json.dumps(batch_locs, ensure_ascii=False),
                "format_instructions": parser.get_format_instructions()
            })
            
            for item in res.get("locations", []):
                results[item["ancient_name"]] = {
                    "modern": item.get("modern_name"),
                    "lat": item.get("lat"),
                    "lng": item.get("lng")
                }
                
        except Exception as e:
            print(f"批次请求失败: {e}")

    out_file = "data/raw/sanguo_geo_dictionary.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
        
    print(f"\n🎉 帅炸了！我们自己用纯 AI 生成的《三国定制版 CHGIS 坐标字典》已保存至 {out_file}！")

if __name__ == "__main__":
    run_geo_encoder()
