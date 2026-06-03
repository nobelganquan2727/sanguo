import os
import sys
import json

# 让脚本可以直接通过 python3 agent/qa_agent.py 运行
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
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

def ask_question(question: str, history: list[dict] = None) -> str:
    llm = get_llm()
    
    # 0. 解析对话历史，保留最近10段对话（即最多20个消息）
    history_to_process = []
    if history:
        for msg in history:
            role = msg.get("role")
            content = msg.get("content")
            if role in ("user", "ai", "assistant") and content:
                history_to_process.append((role, content))
        
        # 避免把当前问题重复算入历史
        if history_to_process and history_to_process[-1][0] == "user" and history_to_process[-1][1] == question:
            history_to_process.pop()
            
        history_to_process = history_to_process[-20:] # 记住之前 10 段对话（即 20 条消息）

    # 1. 意图拆解与问题重写 (Question Decomposition & Intent Analysis)
    print("🧠 正在拆解问题与分析意图...")
    history_text = "\n".join([f"{'用户' if role == 'user' else 'AI'}: {content}" for role, content in history_to_process])
    
    analysis_prompt = f"""
请分析用户的当前问题，并结合对话历史进行意图拆解与问题重写。

=== 对话历史 ===
{history_text or "（无历史对话）"}

=== 当前问题 ===
{question}

请返回一个 JSON 格式的对象（不要包含 markdown 代码块标记，只输出 JSON 文本，确保能被 json.loads 解析），包含以下字段：
- "type": 字符串，只能是以下三者之一：
  1. "relationship": 如果问题是关于两个或多个人物之间的关系、交集、对比、纠葛等。
  2. "fact": 如果问题是查询特定人物/事件/地点的生平、事实或具体问题（如“徐晃最开始跟谁”）。
  3. "generic_chat": 如果是日常问候、询问历史会话内容（如“我刚才问了啥”）、或不需要查询数据库的闲聊与提问。
- "rewritten_question": 结合历史对话重写后的、独立且完整的明确问题。例如，若上文提到“徐晃”，当前问题是“他最开始跟谁”，应重写为“徐晃最开始跟谁”。若当前问题是“我刚才问了啥”，则保持为“我刚才问了啥”。
- "entities": 列表中包含的问题中涉及的核心历史人物或地点名称（如 ["徐晃"] 或 ["刘备", "臧霸"]）。
"""

    analysis_messages = [
        SystemMessage(content="You are a query analysis assistant for a historical knowledge system. You must output JSON only."),
        HumanMessage(content=analysis_prompt)
    ]
    
    try:
        analysis_res = llm.invoke(analysis_messages).content.strip()
        # 清理 markdown codeblock
        if analysis_res.startswith("```json"):
            analysis_res = analysis_res[7:]
        elif analysis_res.startswith("```"):
            analysis_res = analysis_res[3:]
        if analysis_res.endswith("```"):
            analysis_res = analysis_res[:-3]
        analysis_res = analysis_res.strip()
        
        analysis = json.loads(analysis_res)
    except Exception as e:
        print(f"⚠️ 意图拆解解析 JSON 失败: {str(e)}，使用默认降级策略。")
        # 降级策略
        q_type = "fact"
        if any(w in question for w in ["关系", "交集", "纠葛", "对比", "和"]):
            q_type = "relationship"
        elif any(w in question for w in ["刚才", "之前", "什么", "谁", "你好", "哈喽"]):
            if "刚才" in question or "之前" in question:
                q_type = "generic_chat"
        analysis = {
            "type": q_type,
            "rewritten_question": question,
            "entities": []
        }
        
    print(f"📋 意图拆解结果: 类型={analysis.get('type')}, 重写问题='{analysis.get('rewritten_question')}'")

    # 2. 根据不同类型处理
    q_type = analysis.get("type", "fact")
    
    # 2a. 闲聊 / 会话历史查询
    if q_type == "generic_chat":
        print("💬 闲聊或会话历史查询，直接使用大模型回答...")
        chat_messages = [SystemMessage(content="你是精通《三国志》的历史专家。请根据用户的当前问题和对话历史进行回答。")]
        for role, content in history_to_process:
            if role == "user":
                chat_messages.append(HumanMessage(content=content))
            else:
                chat_messages.append(AIMessage(content=content))
        chat_messages.append(HumanMessage(content=question))
        return llm.invoke(chat_messages).content

    # 2b. 图数据库查询流程
    # 针对不同类型生成最合适的 Cypher 提示词
    rewritten_q = analysis.get("rewritten_question", question)
    if q_type == "relationship":
        cypher_prompt = f"""
用户问题: {rewritten_q}

编写 Cypher 查询的准则：
1. 仔细分析用户问题，这属于**人物关系、关联、交集、对比或脉络分析型问题**。你必须使用**宽口径多维召回**的 Cypher 语句（使用模式列表推导式 Pattern Comprehension，将 direct_events, shared_persons, shared_locations, p1_events, p2_events 一并召回，防止产生笛卡尔积）。
2. 请直接输出 Cypher 查询语句，不要有任何其他解释，不要用 markdown code block 包裹，直接输出纯文本。

请为此问题生成最合适的 Cypher 语句：
"""
    else: # fact
        cypher_prompt = f"""
用户问题: {rewritten_q}

编写 Cypher 查询的准则：
1. 仔细分析用户问题，这属于**特定事实或简单条件查询**。请使用标准的 MATCH、WHERE、RETURN 语句，找出相关的 Person、Event、Location 节点和关系，以便获取解决该问题所需的史料数据。
2. 请直接输出 Cypher 查询语句，不要有任何其他解释，不要用 markdown code block 包裹，直接输出纯文本。

请为此问题生成最合适的 Cypher 语句：
"""

    print("🔄 正在思考图查询...")
    cypher_messages = [SystemMessage(content=GRAPH_SCHEMA)]
    for role, content in history_to_process:
        if role == "user":
            cypher_messages.append(HumanMessage(content=content))
        else:
            cypher_messages.append(AIMessage(content=content))
    cypher_messages.append(HumanMessage(content=cypher_prompt))
    
    cypher = llm.invoke(cypher_messages).content.strip()
    
    # 清理可能包含的 markdown 符号
    if cypher.startswith("```cypher"):
        cypher = cypher[9:]
    elif cypher.startswith("```"):
        cypher = cypher[3:]
    if cypher.endswith("```"):
        cypher = cypher[:-3]
    cypher = cypher.strip()
    
    print(f"🔍 执行 Cypher: \n{cypher}\n")
    
    # 执行 Neo4j 图库查询
    graph_results = []
    try:
        graph_results = run_query(cypher)
        print(f"📊 图数据库查到 {len(graph_results)} 条关系记录...")
    except Exception as e:
        print(f"⚠️ 图数据库查询失败 ({str(e)})")

    # 3. 构造回答生成的提示词
    print("✍️ 正在总结回答...")
    if q_type == "relationship":
        answer_prompt = f"""
请根据以下从图数据库中检索出的历史关系数据（包含直接事件、共同关联人、共同地点、以及人物各自的历史轨迹等），回答用户的问题。

作为一名优秀的历史学家，你的回答必须符合以下核心准则：
1. **必须注明正史史料来源与引述原文**：对于你的核心结论，你必须注明《三国志》等正史史料的具体篇目来源（例如《三国志·魏书·徐晃传》），并且必须提取并附上检索数据中对应的【原文】（`source_text` 字段中的正文或裴松之注文等原文）作为佐证。严禁凭空捏造，也绝不可引用《三国演义》等小说的虚构情节。
2. **早年时空交集挖掘（极其重要！）**：你必须极其仔细地检查 p1_events 和 p2_events 中两人早年的事件记录。如果发现两人在早期都曾效力过同一个势力（如袁绍），或者**曾在同一个州郡（如徐州）活动、与同一个诸侯（如陶谦）发生关联**（例如：一方接管了某州/被邀请为州牧，而另一方当时恰好是该州诸侯的部将或活跃在该州），你必须在回答的开头作为单独的重点，详细揭示这段隐藏的“早年同地/同阵营交集”，并合理推断他们在此期间极概率已经结识或有所交集！
3. **深度对比与推理**：将 direct_events, shared_persons, shared_locations 等多维线索有机融合。不仅要讲直接接触，还要讲通过同僚（如荀攸等）产生的间接关系。
4. **还原历史细节与因果**：如果两人的交集是因第三方人物（如举荐、传话等）而起，请梳理出清晰的因果链条，揭示背后的道义或权谋。
5. **历史叙事口吻**：使用沉稳、专业、高屋建瓴的中文历史学者口吻。绝对不可提及任何“图数据库”、“Neo4j”、“Cypher”、“检索”、“字段”、“JSON”、“列表”、“结果”等底层技术/数据名词，直接以史书叙事方式呈现。
6. **合情推理**：如果检索数据为空或信息量不足，请在说明史料无直接记载的同时，基于你自身强大的《三国志》真实史学知识进行合情合理的分析和补充，并注明推演所依据的正史篇章。

用户问题: {rewritten_q}

=== 检索到的多维关系数据 (JSON) ===
{json.dumps(graph_results, ensure_ascii=False)}
"""
    else: # fact
        answer_prompt = f"""
请根据以下从图数据库中检索出的历史事实数据，回答用户的问题。

请以一名优秀的《三国志》历史学家口吻回答，准则如下：
1. **必须注明正史史料来源与引述原文**：对于你的核心结论，你必须注明《三国志》等正史史料的具体篇目来源（例如《三国志·魏书·武帝纪》），并且必须提取并附上检索数据中对应的【原文】（`source_text` 字段中的正文或裴松之注文等原文）作为佐证。严禁引用《三国演义》等小说的虚构情节。
2. **直接且准确**：清晰直白地回答用户的问题，给出史实原因或背景。
3. **细节丰富**：结合检索到的事件和时间段，适当展开细节（如人物字号、时间、所涉其他次要人物等）。
4. **不要提及底层技术**：绝对不可提及任何“图数据库”、“Neo4j”、“Cypher”、“检索”、“字段”、“JSON”、“列表”、“结果”等底层技术/数据名词，直接以史书叙事方式呈现。
5. **合情推理**：如果检索数据为空或信息量不足，请在说明史料无直接记载的同时，基于你自身强大的《三国志》真实史学知识进行分析和解答，并说明推演所依据的正史部分。

用户问题: {rewritten_q}

=== 检索到的历史数据 (JSON) ===
{json.dumps(graph_results, ensure_ascii=False)}
"""

    answer_messages = [SystemMessage(content="你是精通《三国志》的历史专家。")]
    for role, content in history_to_process:
        if role == "user":
            answer_messages.append(HumanMessage(content=content))
        else:
            answer_messages.append(AIMessage(content=content))
    answer_messages.append(HumanMessage(content=answer_prompt))
    
    answer = llm.invoke(answer_messages).content
    return answer

if __name__ == "__main__":
    # 测试一下
    q = "刘备和臧霸有什么关系？"
    print(f"🧑‍💻 问题: {q}")
    print("-" * 40)
    ans = ask_question(q)
    print("-" * 40)
    print(f"🤖 回答:\n{ans}")
