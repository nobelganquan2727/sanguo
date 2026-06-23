import os
import json
import redis.asyncio as aioredis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Setup a global connection pool
redis_client = aioredis.from_url(
    REDIS_URL,
    encoding="utf-8",
    decode_responses=True
)

redis_available = False

async def check_redis_connectivity():
    global redis_available
    try:
        await redis_client.ping()
        redis_available = True
        print("🚀 Successfully connected to Redis session store!")
    except Exception as e:
        redis_available = False
        print(f"⚠️ Redis connection failed: {e}. Session memory will fallback to request-passed history.")
    return redis_available

async def get_session_history(session_id: str) -> list[dict]:
    if not redis_available:
        return []
    try:
        raw_msgs = await redis_client.lrange(session_id, 0, -1)
        if raw_msgs:
            return [json.loads(m) for m in raw_msgs]
    except Exception as e:
        print(f"⚠️ Error fetching session from Redis: {e}.")
    return []

async def save_session_history(session_id: str, question: str, answer: str):
    if not redis_available:
        return
    try:
        # Avoid saving if AI answers with fallback warning/error messages
        if answer and not ("病体抱恙" in answer or "简牍翻阅多有不便" in answer):
            await redis_client.rpush(session_id, json.dumps({"role": "user", "content": question}, ensure_ascii=False))
            await redis_client.rpush(session_id, json.dumps({"role": "ai", "content": answer}, ensure_ascii=False))
            await redis_client.expire(session_id, 3600)  # 1 hour TTL
    except Exception as e:
        print(f"⚠️ Error saving session to Redis: {e}")
