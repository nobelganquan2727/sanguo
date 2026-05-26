import os
import json
import glob
import concurrent.futures
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from typing import List, Optional

# Define Pydantic schema for structured output
class RelationDetail(BaseModel):
    to: str = Field(description="关系目标人物的姓名，例如: '关羽'")
    type: str = Field(description="具体关系描述，例如: '从子', '结拜兄弟', '托孤重臣'")
    relation_type: str = Field(description="严格在以下大类中选择: 'KINSHIP'(血缘亲属), 'ALLY'(同盟/好友/同僚), 'ENEMY'(宿敌/对手), 'RULER_SUBJECT'(主臣关系), 'RECOMMENDED'(引荐/提拔/发掘)")

class StaticMetadata(BaseModel):
    name: str = Field(description="人物姓名，例如: '荀彧'")
    hometown: Optional[str] = Field(description="历史籍贯郡县，精确到郡或县，例如: '颍川颍阴'。如无记载填'未知'")
    clan: Optional[str] = Field(description="所属的世家大族名称，例如: '颍川荀氏'。若非世家大族，填'无'")
    relations: List[RelationDetail] = Field(default=[], description="该人物在《三国志》及裴注中最核心的社交圈关系列表（限5-10个最重要的人物）")

def extract_single_character(character_name: str, llm) -> Optional[dict]:
    """
    通过大模型提取单个角色的静态元数据
    """
    parser = JsonOutputParser(pydantic_object=StaticMetadata)
    prompt = ChatPromptTemplate.from_messages([
        ("system", """你是一位精通《三国志》及裴松之注的历史研究专家。
你的任务是根据你的历史知识库，为指定的三国人物提取静态元数据（籍贯、世族、最核心的人物关系网）。

【提取规范】
1. **籍贯(hometown)**：必须是东汉末年至三国时期的历史地名（如'沛国谯县'、'琅邪阳都'），不要写现代地名。
2. **世族(clan)**：必须是当时公认的世家大族（如'颍川荀氏'、'弘农杨氏'、'吴郡陆氏'）。普通寒门或无家族背景的填'无'。
3. **人物关系(relations)**：
   - 数量限制：提取最核心的 3 到 8 个关系，不可泛滥。
   - `relation_type` 必须严格是以下 5 个英文单词之一：
     * `KINSHIP` : 父母、兄弟、子女、族亲、姻亲
     * `ALLY` : 结拜、挚友、生死之交、核心政治盟友
     * `ENEMY` : 宿敌、战场死敌、死对头
     * `RULER_SUBJECT` : 君臣关系（主公与部下）
     * `RECOMMENDED` : 举荐人、发掘人、恩师
   - 请保证 `to` 属性的人物名字是《三国志》中标准的姓名。

格式要求：
{format_instructions}
"""),
        ("user", "请为三国历史人物【{character_name}】提取并输出静态元数据。")
    ])

    chain = prompt | llm | parser
    try:
        res = chain.invoke({
            "character_name": character_name,
            "format_instructions": parser.get_format_instructions()
        })
        return res
    except Exception as e:
        print(f"❌ 提取人物 {character_name} 失败: {e}")
        return None

def main():
    load_dotenv()
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("请先在 .env 文件中设置 DEEPSEEK_API_KEY 环境变量！")

    llm = ChatOpenAI(
        model="deepseek-chat", 
        api_key=api_key, 
        base_url="https://api.deepseek.com/v1",
        max_tokens=2048,
        temperature=0.1,
        model_kwargs={"response_format": {"type": "json_object"}}
    )

    output_file = "data/character_static_metadata.json"
    
    # 1. 载入已有进度，支持断点续传
    existing_data = {}
    if os.path.exists(output_file):
        try:
            with open(output_file, "r", encoding="utf-8") as f:
                records = json.load(f)
                existing_data = {r["name"]: r for r in records}
            print(f"📂 发现已有静态元数据记录：{len(existing_data)} 条。将采用断点续传。")
        except Exception as e:
            print(f"⚠️ 读取已有数据文件失败，将重新生成: {e}")

    # 2. 扫描 data/raw 下已有的所有事件 JSON 文件，获取全量传主名单
    event_files = glob.glob("data/raw/*_events.json")
    all_characters = []
    for f in event_files:
        char_name = os.path.basename(f).replace("_events.json", "")
        # 过滤掉一些特殊非人物文件（如少数民族传记等）
        if char_name not in ["东夷", "乌丸", "鲜卑"]:
            all_characters.append(char_name)

    print(f"📦 共检测到本地已导出的传主人物：{len(all_characters)} 人。")
    
    # 筛选出尚未提取的人物
    todo_characters = [c for c in all_characters if c not in existing_data]
    print(f"⚡ 还需要提取：{len(todo_characters)} 人。")

    if not todo_characters:
        print("🎉 所有人物的静态关系网络均已提取完毕！无需再次提取。")
        return

    # 3. 多线程并行调用 DeepSeek API 提取静态网络 (控制并发数防限频)
    max_workers = 5
    print(f"🚀 开始多线程并发提取（并发数：{max_workers}），请稍候...")

    # 保存结果的列表，以已有的数据为底座
    final_records = list(existing_data.values())

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 建立 future 到 角色名 的映射
            future_to_char = {
                executor.submit(extract_single_character, char, llm): char 
                for char in todo_characters
            }
            
            completed = 0
            for future in concurrent.futures.as_completed(future_to_char):
                char = future_to_char[future]
                completed += 1
                try:
                    result = future.result()
                    if result:
                        final_records.append(result)
                        print(f"[{completed}/{len(todo_characters)}] ✅ 成功提取 {char} 的静态关系网络！")
                        
                        # 每次提取成功即时保存，防止异常崩溃丢失进度
                        with open(output_file, "w", encoding="utf-8") as f:
                            json.dump(final_records, f, ensure_ascii=False, indent=2)
                    else:
                        print(f"[{completed}/{len(todo_characters)}] ⚠️ {char} 提取结果为空")
                except Exception as exc:
                    print(f"[{completed}/{len(todo_characters)}] ❌ {char} 产生异常: {exc}")
                    
    except KeyboardInterrupt:
        print("\n🛑 收到中断信号，正在保存当前已提取的进度...")
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(final_records, f, ensure_ascii=False, indent=2)
        print("💾 进度已安全保存。您可以随时重跑此脚本断点续传。")
        return

    print(f"\n🎉 全量静态元数据提取完毕！数据已保存至：{output_file}")
    print("现在您可以直接运行 `python3 scripts/import_static_metadata.py` 增量缝合到图数据库了！")

if __name__ == "__main__":
    main()
