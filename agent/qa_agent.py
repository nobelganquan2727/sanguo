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
请直接输出 Cypher 查询语句，不要有任何其他解释，不要用 markdown code block 包裹，直接输出纯文本。
如果遇到模糊查询，可以使用 `CONTAINS` 或者正则。
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
请根据以下从 **Neo4j 图数据库（结构化关系数据）** 中检索到的历史信息，回答用户的问题。

要求：
1. 用中文回答，语气自然流畅，符合历史学家的口吻。
2. 绝对不要在回答中提及"图数据库"、"Neo4j"、"查询结果"等底层技术词汇。直接以历史叙事口吻进行叙述。
3. 如果检索结果为空，请委婉说明在当前史料图谱中没有找到直接相关的记录，并基于你的历史知识简单补充。

用户问题: {question}

=== 图谱关系数据 (JSON) ===
{json.dumps(graph_results, ensure_ascii=False)}
"""
    answer = llm.invoke([
        SystemMessage(content="你是精通《三国志》的历史专家。"),
        HumanMessage(content=answer_prompt)
    ]).content
    
    return answer

if __name__ == "__main__":
    # 测试一下
    q = "关羽和曹操有什么关联？"
    print(f"🧑‍💻 问题: {q}")
    print("-" * 40)
    ans = ask_question(q)
    print("-" * 40)
    print(f"🤖 回答:\n{ans}")
