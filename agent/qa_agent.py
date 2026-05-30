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

# === ChromaDB 向量数据库初始化 ===
import chromadb
from scripts.build_vector_db import LocalBgem3EmbeddingFunction

load_dotenv()

_chroma_client = None
_chroma_collection = None

def get_chroma_collection():
    global _chroma_client, _chroma_collection
    if _chroma_collection is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        chroma_db_dir = os.path.join(base_dir, "data", "chroma_db")
        _chroma_client = chromadb.PersistentClient(path=chroma_db_dir)
        bgem3_ef = LocalBgem3EmbeddingFunction()
        _chroma_collection = _chroma_client.get_collection(
            name="sanguozhi_events_bgem3",
            embedding_function=bgem3_ef
        )
    return _chroma_collection

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
        print(f"⚠️ 图数据库查询失败 ({str(e)})，将仅依赖向量库...")
        
    # 3. 执行 Chroma 向量库查询 (从向量库召回详细事件文献)
    print("🔍 正在并行进行 Chroma 语义检索...")
    vector_context = ""
    try:
        collection = get_chroma_collection()
        vector_res = collection.query(
            query_texts=[question],
            n_results=3
        )
        if vector_res and vector_res.get('documents') and len(vector_res['documents']) > 0:
            docs = vector_res['documents'][0]
            metas = vector_res['metadatas'][0]
            vector_docs = []
            for idx, (doc, meta) in enumerate(zip(docs, metas)):
                person = meta.get("person_name", "未知")
                title = meta.get("title", "无标题")
                vector_docs.append(f"【文献史料 {idx+1}】(人物: {person}, 标题: {title})\n{doc}")
            vector_context = "\n\n".join(vector_docs)
            print(f"📄 向量库成功召回 {len(docs)} 条详细文献史料...")
    except Exception as ve:
        print(f"⚠️ Chroma 检索失败: {ve}")
        
    # 4. 融合两种数据源并用 DeepSeek 生成大白话回答 (Graph + Vector RAG)
    print("✍️ 正在融合多源数据并总结回答...")
    answer_prompt = f"""
请根据以下从 **Neo4j 图数据库（结构化关系数据）** 和 **Chroma 向量数据库（非结构化正史事件文献）** 中检索到的历史信息，融会贯通，回答用户的问题。

要求：
1. 用中文回答，语气自然流畅，符合历史学家的口吻。
2. 将这两种数据源检索出的信息完美融合，互相补充细节。例如，利用图谱的强人物关系去理解事件网络，同时用向量库的详细原文故事丰富内容。
3. 绝对不要在回答中提及"图数据库"、"向量数据库"、"Neo4j"、"Chroma"、"查询结果"等底层技术词汇。直接以历史叙叙的口吻叙述。
4. 如果检索结果均为空，请委婉说明在当前史料图谱和文献中没有找到直接相关的记录，并基于你的历史知识简单补充。

用户问题: {question}

=== 数据源 A：图关系数据 (JSON) ===
{json.dumps(graph_results, ensure_ascii=False)}

=== 数据源 B：语义事件文献 (Text) ===
{vector_context if vector_context else "（无相关文献）"}
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
