import os
import json
import argparse
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from typing import List

class SanguoEvent(BaseModel):
    事件标题: str = Field(description="事件的精炼标题，不超过15个字")
    时间: str = Field(description="历史时间，例如：建安五年（200年）")
    地点: str = Field(description="发生地，多个地点用顿号分隔，例如：许都、下邳")
    相关人物: List[str] = Field(description="事件的核心人物数组，例如：['刘备', '关羽', '曹操']")
    事件简介: str = Field(description="用白话文详细描述该事件的起步、经过和结果")
    事件类型: str = Field(description="如：军事征伐、政治决策、内部叛乱等")
    影响和结果: str = Field(alias="影响/结果", description="该事件对天下大势或人物命运的深远影响")
    原文: str = Field(description="相关的文言文原文段落")

class EventsForOnePerson(BaseModel):
    events: List[SanguoEvent] = Field(description="当前关注传主的专属历史事件合集")

class CharacterList(BaseModel):
    characters: List[str] = Field(description="文档中包含的主要传主姓名数组")

def extract_events_from_text(input_file: str, output_dir: str):
    print(f"正在读取文件: {input_file}")
    with open(input_file, 'r', encoding='utf-8') as f:
        raw_text = f.read()

    # 1. 挂载环境
    load_dotenv()
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("请先设置 DEEPSEEK_API_KEY 环境变量！")

    llm = ChatOpenAI(
        model="deepseek-chat", 
        api_key=api_key, 
        base_url="https://api.deepseek.com/v1",
        max_tokens=8192,
        temperature=0.1,
        model_kwargs={"response_format": {"type": "json_object"}}
    )

    # 步骤 1：让模型先“审题”，看合传里到底挂了多少个人名
    print("📍 [Step 1] 正在让模型预览全文，分析合传中包含哪些核心人物...")
    char_parser = JsonOutputParser(pydantic_object=CharacterList)
    char_prompt = ChatPromptTemplate.from_messages([
        ("system", "你是一名史料分析专家。任务是通读下面的《三国志》合传原文，识别出文章主要记载了哪几个核心传主。\n请精准梳理并输出核心人物名字数组（如 ['关羽', '张飞', '马超', '赵云']）。\n{format_instructions}"),
        ("user", "合传原文：\n{text}")
    ])
    
    try:
        # 传主名字通常在全篇都可能提到，这里把全文或者前部分送进去皆可
        char_res = (char_prompt | llm | char_parser).invoke({
            "text": raw_text,
            "format_instructions": char_parser.get_format_instructions()
        })
        characters = char_res.get("characters", [])
        print(f"✅ 从文章中成功提取出大传主清单：{characters}")
    except Exception as e:
        print(f"❌ 识别传主失败：{e}")
        return

    # 步骤 2：拿着提取出来的人员清单，进行“分批循环聚焦提取”
    event_parser = JsonOutputParser(pydantic_object=EventsForOnePerson)
    event_prompt = ChatPromptTemplate.from_messages([
        ("system", """你是一位严谨的三国历史数据结构化专家。
目标：阅读提供的《三国志》合传文言文，现在请你**只针对名为【{person_name}】的传主**，提取属于他的史料并结构化。

核心要求：
1. 聚光灯效应：你的目光请紧住【{person_name}】一个人，不要管这篇合传里的其他主角，除非事件与他深度相关！
2. 严格基于原文提取，不可凭空捏造。
3. 将文言文原文段落准确地填入“原文”字段，保持古言。
4. 用通俗易懂的现代白话文撰写“事件简介”。
5. 如果找不到明确的时间或地点，请填“不详”。
6. ⚠️极其重要：输出的字段内容中，如果要引用说话等内容，请绝对禁止使用双引号（""），必须全部替换为单引号（''）或中文引号（「」），否则会导致 JSON 解析失败！

格式要求：
{format_instructions}
"""),
        ("user", "请紧紧围绕传主【{person_name}】，提取以下《三国志》文本中的史料：\n\n{text}")
    ])

    chain = event_prompt | llm | event_parser

    os.makedirs(output_dir, exist_ok=True)

    # 循环遍历每个人物
    success_count = 0
    for person in characters:
        file_name = os.path.join(output_dir, f"{person}_events.json")
        
        # 【断点续传/去重】判断如果当前人物的数据已存在就不重复浪费 API 额度提取了
        if os.path.exists(file_name):
            print(f"⏭️  [{person}] 的史料文件早已存在 ({file_name})，安全跳过提取。")
            success_count += 1
            continue
            
        print(f"\n🔍 [Step 2] 正在专注剥离【{person}】的史料...")
        try:
            result = chain.invoke({
                "person_name": person,
                "text": raw_text,  # 每次输入全文，但不担心爆内存，由于提示词限制，输出只会是单人的内容
                "format_instructions": event_parser.get_format_instructions()
            })
            events = result.get('events', [])
            
            with open(file_name, 'w', encoding='utf-8') as f:
                json.dump(events, f, ensure_ascii=False, indent=2)
                
            print(f"✅ [{person}] 提取成功！共提取 {len(events)} 个事件，保存至：{file_name}")
            success_count += 1
        except Exception as e:
            print(f"❌ 提取 {person} 时失败: {e}")
            
            
    return success_count > 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="使用 LangChain 分批提取合传史料算法")
    parser.add_argument("--input", default="sgraw/shu/三国志_卷三十六 蜀书六 关张马黄赵传第六.txt", help="输入的合传 txt 文件")
    parser.add_argument("--output_dir", default="data/raw", help="输出多个 JSON 文件的保护目录")
    
    args = parser.parse_args()
    extract_events_from_text(args.input, args.output_dir)
