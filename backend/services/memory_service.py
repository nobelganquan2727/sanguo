import json
import asyncio
import traceback
from sqlalchemy.orm import Session
from db.mysql import SessionLocal, UserProfile, UserMemory
from agent.tools import get_llm
from langchain_core.messages import SystemMessage, HumanMessage

MEMORY_EXTRACTOR_PROMPT = """你是一个高精度的用户画像与长期记忆提取助手。
你的任务是阅读用户与“三国历史智能体”的最新一轮对话，并提取/更新用户的长期记忆。

【输入数据】:
1. 用户当前提问: {question}
2. 智能体最新回答: {answer}
3. 现有的长期记忆:
{existing_memory}

【提取与合并任务说明】:
1. 评估用户的偏好倾向：喜欢“detailed（详细引经据典）”还是“concise（简洁直奔主题）”？
2. 评估用户的知识水平：是“beginner（初学者，需要通俗解释）”还是“expert（学术专家，能看懂文言文与考证）”？
3. 提取对话中涉及的核心历史话题（如特定人物、战役、地名），总结用户对这些话题的已有认知或兴趣。
   - 【重要规则 1】：关于单个话题的总结字数**绝对不能超过 100 字**，必须高度提炼、精简为一两句话。
   - 【重要规则 2】：如果该话题在现有长期记忆中不存在，则新建该话题的总结；如果已存在，则**必须将新提炼的信息与现有长期记忆合并、压缩并更新**，不要直接追加，必须融合成一句话！
   - 【重要规则 3】：每次对话最多提取或更新 **2 个最核心的话题**。

请必须以 JSON 格式输出，确保没有 markdown 标记（严禁使用 ```json 包裹），可以直接被 json.loads 解析，包含以下 key:
{{
  "preference": "detailed" 或 "concise",
  "knowledge_level": "beginner" 或 "expert",
  "new_or_updated_memories": {{
     "话题名称": "更新后的合并总结"
  }}
}}
"""

def format_user_memory(profile: UserProfile, memories: list[UserMemory]) -> str:
    """
    Formats the MySQL user profile and memories into a structured system prompt block.
    This helps the agent personalize its response tone, depth, and recall past chats.
    """
    if not profile:
        return ""
        
    pref_cn = "详实详尽（偏好引经据典，详列史料）" if profile.preference == 'detailed' else "精简指要（直奔主题，言简意赅）"
    lvl_cn = "学术专家模式（多引《三国志》及古书原文）" if profile.knowledge_level == 'expert' else "历史入门模式（通俗白话，生动易懂）"
    
    memory_block = f"""
=== 📥 阁下（用户）的长期记忆与偏好 ===
- 阁下偏好：{pref_cn}
- 阁下知识水平：{lvl_cn}
"""
    if memories:
        memory_block += "- 阁下在先前会话中探讨过的话题与已掌握之概念（参考此信息以避免重复基础介绍，并展现记忆连续性）：\n"
        for mem in memories:
            memory_block += f"  * 【{mem.topic}】: {mem.summary}\n"
            
    memory_block += "========================================\n"
    return memory_block


def _fetch_existing_memories_sync(user_id: str) -> tuple[str, str, str]:
    """Helper to fetch profile traits and existing memories from MySQL synchronously."""
    db = SessionLocal()
    try:
        profile = db.query(UserProfile).filter_by(user_id=user_id).first()
        if not profile:
            profile = UserProfile(user_id=user_id)
            db.add(profile)
            db.commit()
            db.refresh(profile)
            
        memories = db.query(UserMemory).filter_by(user_id=user_id).all()
        existing_mem_desc = "\n".join([f"- {m.topic}: {m.summary}" for m in memories])
        return profile.preference, profile.knowledge_level, existing_mem_desc
    finally:
        db.close()


def _save_consolidated_memories_sync(user_id: str, data: dict):
    """Helper to save, merge, and evict memories in MySQL synchronously."""
    db = SessionLocal()
    try:
        profile = db.query(UserProfile).filter_by(user_id=user_id).first()
        if not profile:
            profile = UserProfile(user_id=user_id)
            db.add(profile)
            
        profile.preference = data.get("preference", profile.preference)
        profile.knowledge_level = data.get("knowledge_level", profile.knowledge_level)
        
        new_mems = data.get("new_or_updated_memories", {})
        for topic, summary in new_mems.items():
            topic = topic.strip()
            if not topic:
                continue
                
            existing_mem = db.query(UserMemory).filter_by(user_id=user_id, topic=topic).first()
            if existing_mem:
                existing_mem.summary = summary
            else:
                new_rec = UserMemory(user_id=user_id, topic=topic, summary=summary)
                db.add(new_rec)
                
        db.commit()
        
        # Apply LRU eviction if memories exceed 20 topics
        all_mems = db.query(UserMemory).filter_by(user_id=user_id).order_by(UserMemory.last_discussed_at.desc()).all()
        if len(all_mems) > 20:
            to_delete = all_mems[20:]
            for m in to_delete:
                db.delete(m)
            db.commit()
            print(f"🗑️ [LTM] Evicted {len(to_delete)} oldest memories for user {user_id} (kept top 20).")
            
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


async def consolidate_memory_task(user_id: str, question: str, actual_answer: str):
    """
    Asynchronous background task to extract, merge, and save new user memories to MySQL.
    Uses asyncio.to_thread to run synchronous SQLAlchemy calls in a background thread
    to prevent blocking the uvicorn event loop.
    """
    try:
        # 1. Fetch profile and memories in a background thread (non-blocking)
        pref, kl, existing_mem_desc = await asyncio.to_thread(_fetch_existing_memories_sync, user_id)
        
        # 2. Format prompt for LLM extractor
        prompt = MEMORY_EXTRACTOR_PROMPT.format(
            question=question,
            answer=actual_answer,
            existing_memory=existing_mem_desc or "（无）"
        )
        
        # 3. Call LLM to extract memory (async, naturally non-blocking)
        llm = get_llm("cheap")
        
        res_msg = await llm.ainvoke([
            SystemMessage(content="You are a JSON memory extractor. Output raw JSON only."),
            HumanMessage(content=prompt)
        ])
        
        res_content = res_msg.content.strip()
        if res_content.startswith("```json"):
            res_content = res_content[7:]
        elif res_content.startswith("```"):
            res_content = res_content[3:]
        if res_content.endswith("```"):
            res_content = res_content[:-3]
        res_content = res_content.strip()
        print(f"🔍 [LTM Debug] Raw LLM Response:\n{res_content}")
        
        data = json.loads(res_content)
        
        # 4. Save and consolidate in a background thread (non-blocking)
        await asyncio.to_thread(_save_consolidated_memories_sync, user_id, data)
        print(f"💾 [LTM] Successfully updated and consolidated long-term memory for user: {user_id}")
        
    except Exception as e:
        print(f"⚠️ [LTM] Memory consolidation failed: {e}")
        traceback.print_exc()
