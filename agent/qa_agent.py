import os
import sys
import json

# 让脚本可以直接通过 python3 agent/qa_agent.py 运行
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from dotenv import load_dotenv
from agent.schema import GRAPH_SCHEMA
from agent.graph_client import run_query

load_dotenv()

def get_llm():
    return ChatOpenAI(
        model="deepseek-chat", 
        api_key=os.environ.get("DEEPSEEK_API_KEY"), 
        base_url="https://api.deepseek.com/v1",
        max_tokens=8192,
        temperature=0
    )

def ask_question(question: str) -> str:
    llm = get_llm()
    
    # 1. Text to Cypher (从 Neo4j 召回结构化关系)
    cypher_prompt = f"""
用户问题: {question}

编写 Cypher 查询的准则：
1. 仔细分析用户问题，如果属于**人物关系、关联、交集、对比或脉络分析型问题**（例如“A和B的关系”、“A和B有什么瓜葛”），你必须使用**宽口径多维召回**的 Cypher 语句（使用模式列表推导式 Pattern Comprehension，将 direct_events, shared_persons, shared_locations, p1_events, p2_events 一并召回，防止产生笛卡尔积）。
2. 如果是特定事实或简单条件查询（如“曹操哪年迎奉天子”、“赤壁在哪个地方”），则使用标准的 MATCH 或 WHERE 进行精准查询。
3. 请直接输出 Cypher 查询语句，不要有任何其他解释，不要用 markdown code block 包裹，直接输出纯文本。

请为此问题生成最合适的 Cypher 语句：
"""
    print("🔄 正在思考图查询...")
    cypher = llm.invoke([
        SystemMessage(content=GRAPH_SCHEMA),
        HumanMessage(content=cypher_prompt)
    ]).content.strip()
    
    # 清理可能包含的 markdown 符号
    if cypher.startswith("```cypher"):
        cypher = cypher[9:]
    elif cypher.startswith("```"):
        cypher = cypher[3:]
    if cypher.endswith("```"):
        cypher = cypher[:-3]
    cypher = cypher.strip()
    
    print(f"🔍 执行 Cypher: \n{cypher}\n")
    
    # 2. 执行 Neo4j 图库查询
    graph_results = []
    try:
        graph_results = run_query(cypher)
        print(f"📊 图数据库查到 {len(graph_results)} 条关系记录...")
    except Exception as e:
        print(f"⚠️ 图数据库查询失败 ({str(e)})")
        
    # 3. 用 DeepSeek 生成回答
    print("✍️ 正在根据图谱数据总结回答...")
    answer_prompt = f"""
请根据以下从图数据库中检索出的历史关系数据（包含直接事件、共同关联人、共同地点、以及人物各自的历史轨迹等），回答用户的问题。

作为一名优秀的历史学家，你的回答必须包含以下核心层次：
1. **早年时空交集挖掘（极其重要！）**：你必须极其仔细地检查 p1_events 和 p2_events 中两人早年的事件记录。如果发现两人在早期都曾效力过同一个势力（如袁绍），或者**曾在同一个州郡（如徐州）活动、与同一个诸侯（如陶谦）发生关联**（例如：一方接管了某州/被邀请为州牧，而另一方当时恰好是该州诸侯的部将或活跃在该州），你必须在回答的开头作为单独的重点，详细揭示这段隐藏的“早年同地/同阵营交集”，并合理推断他们在此期间极大概率已经结识或有所交集！
2. **深度对比与推理**：将 direct_events, shared_persons, shared_locations 等多维线索有机融合。不仅要讲直接接触，还要讲通过同僚（如荀攸等）产生的间接关系。
3. **还原历史细节与因果**：如果两人的交集是因第三方人物（如举荐、传话等）而起，请梳理出清晰的因果链条，揭示背后的道义或权谋。
4. **历史叙事口吻**：使用沉稳、专业、高屋建瓴的中文历史学者口吻。绝对不可提及任何“图数据库”、“Neo4j”、“Cypher”、“检索”、“字段”、“JSON”、“列表”、“结果”等底层技术/数据名词，直接以史书叙事方式呈现。
5. **合情推理**：如果检索数据为空或信息量不足，请在说明史料无直接记载的同时，基于你自身强大的《三国志》真实史学知识进行合情合理的分析和补充。

用户问题: {question}

=== 检索到的多维关系数据 (JSON) ===
{json.dumps(graph_results, ensure_ascii=False)}
"""
    answer = llm.invoke([
        SystemMessage(content="你是精通《三国志》的历史专家。"),
        HumanMessage(content=answer_prompt)
    ]).content
    
    return answer

if __name__ == "__main__":
    # 测试一下
    q = "刘备和臧霸有什么关系？"
    print(f"🧑‍💻 问题: {q}")
    print("-" * 40)
    ans = ask_question(q)
    print("-" * 40)
    print(f"🤖 回答:\n{ans}")
