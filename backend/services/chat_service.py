import json
import asyncio
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from agent.qa_agent import ask_question_stream
from db.redis import get_session_history, save_session_history
from db.mysql import UserProfile, UserMemory
from services.memory_service import format_user_memory, consolidate_memory_task

async def handle_ask_stream(
    question: str, 
    history: list[dict], 
    session_id: str = None, 
    user_id: str = None,
    db: Session = None
) -> StreamingResponse:
    use_redis = False
    active_history = history
    user_memory_block = ""
    
    # 1. Resolve short-term session history from Redis
    if session_id:
        print(f"🔑 [Redis Debug] Incoming request with session_id: {session_id}")
        redis_hist = await get_session_history(session_id)
        if redis_hist:
            print(f"📖 [Redis Debug] Successfully loaded {len(redis_hist)} messages from Redis history.")
            active_history = redis_hist
            use_redis = True
        else:
            print(f"❓ [Redis Debug] No history found in Redis for session_id: {session_id}. Falling back to client-provided history (len: {len(history)}).")
            if len(history) == 0:
                use_redis = True
    else:
        print("ℹ️ [Redis Debug] No session_id provided. Using client-provided history directly.")
        
    # 2. Resolve cross-session long-term memory (LTM) from MySQL
    if user_id and db:
        try:
            print(f"🧠 [LTM] Fetching profile and memories for user: {user_id}")
            profile = db.query(UserProfile).filter_by(user_id=user_id).first()
            if not profile:
                profile = UserProfile(user_id=user_id)
                db.add(profile)
                db.commit()
                db.refresh(profile)
                
            # Fetch Top-5 most recently discussed memories (sliding window hard-cap!)
            memories = db.query(UserMemory).filter_by(user_id=user_id)\
                         .order_by(UserMemory.last_discussed_at.desc())\
                         .limit(5).all()
                         
            user_memory_block = format_user_memory(profile, memories)
            print(f"🧠 [LTM] Loaded {len(memories)} memory topics. Injected memory block.")
        except Exception as db_err:
            print(f"⚠️ [LTM] Failed to load user memory: {db_err}")
            user_memory_block = ""

    async def sse_generator():
        collected_chunks = []
        async for chunk in ask_question_stream(question, active_history, user_memory_block=user_memory_block):
            yield chunk
            try:
                data = json.loads(chunk.strip())
                if data.get("type") == "text":
                    collected_chunks.append(data.get("content", ""))
            except Exception:
                pass
        
        full_answer = "".join(collected_chunks).strip()
        
        # 3. Save to short-term session history in Redis
        if use_redis and session_id and full_answer:
            if not ("病体抱恙" in full_answer or "简牍翻阅多有不便" in full_answer):
                print(f"💾 [Redis Debug] Attempting to save new dialogue turn to Redis for session_id: {session_id}...")
                await save_session_history(session_id, question, full_answer)
                print(f"✅ [Redis Debug] Successfully appended user question & AI answer to Redis for session_id: {session_id}.")
            else:
                print(f"⚠️ [Redis Debug] Skipped saving to Redis (empty or fallback answer detected).")
                
        # 4. Consolidate and update long-term memory asynchronously in the background
        if user_id and full_answer:
            if not ("病体抱恙" in full_answer or "简牍翻阅多有不便" in full_answer):
                print(f"🧠 [LTM] Spawning background task to consolidate long-term memory for user: {user_id}")
                asyncio.create_task(consolidate_memory_task(user_id, question, full_answer))

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream"
    )

