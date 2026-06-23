import json
from fastapi.responses import StreamingResponse
from agent.qa_agent import ask_question_stream
from db.redis import get_session_history, save_session_history

async def handle_ask_stream(question: str, history: list[dict], session_id: str = None) -> StreamingResponse:
    use_redis = False
    active_history = history
    
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
                # Session ID is provided but Redis was empty or failed,
                # fallback to client history, but flag use_redis=True so we write back to Redis later
                use_redis = True
    else:
        print("ℹ️ [Redis Debug] No session_id provided. Using client-provided history directly.")

    async def sse_generator():
        collected_chunks = []
        async for chunk in ask_question_stream(question, active_history):
            yield chunk
            try:
                data = json.loads(chunk.strip())
                if data.get("type") == "text":
                    collected_chunks.append(data.get("content", ""))
            except Exception:
                pass
        
        if use_redis and session_id:
            full_answer = "".join(collected_chunks).strip()
            if full_answer and not ("病体抱恙" in full_answer or "简牍翻阅多有不便" in full_answer):
                print(f"💾 [Redis Debug] Attempting to save new dialogue turn to Redis for session_id: {session_id}...")
                await save_session_history(session_id, question, full_answer)
                print(f"✅ [Redis Debug] Successfully appended user question & AI answer to Redis for session_id: {session_id}.")
            else:
                print(f"⚠️ [Redis Debug] Skipped saving to Redis (empty or fallback answer detected).")

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream"
    )

