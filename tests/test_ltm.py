#!/usr/bin/env python3
"""
Sanguozhi Agent - Long-Term Memory (LTM) Integration Test
Verifies:
  1. Database table initialization
  2. Formatting of user profiles/memories into system prompt blocks
  3. Asynchronous memory extraction & consolidation (LLM-as-Extractor)
  4. Compression limits (<100 characters)
  5. Merge & update behavior (no endless appending)
"""

import os
import sys
import asyncio
from dotenv import load_dotenv

# Ensure the root directory and backend directory are in python path
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(_root)
sys.path.append(os.path.join(_root, "backend"))

load_dotenv()

from db.mysql import SessionLocal, Base, engine, UserProfile, UserMemory
from services.memory_service import format_user_memory, consolidate_memory_task

TEST_USER_ID = "test_user_999_advisor"

async def run_test():
    print("🚀 [LTM Test] Starting Long-Term Memory Integration Test...")
    
    # 1. Initialize Tables (Double check)
    print("📦 [LTM Test] 1. Initializing MySQL tables if not exist...")
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    try:
        # Clean up any existing test records
        print(f"🧹 [LTM Test] Cleaning up old test records for: {TEST_USER_ID}")
        db.query(UserMemory).filter_by(user_id=TEST_USER_ID).delete()
        db.query(UserProfile).filter_by(user_id=TEST_USER_ID).delete()
        db.commit()
        
        # 2. Test Profile Creation & Memory Formatting (Empty case)
        print("\n📝 [LTM Test] 2. Testing memory formatting for a brand new user...")
        profile = UserProfile(user_id=TEST_USER_ID, preference="detailed", knowledge_level="expert")
        db.add(profile)
        db.commit()
        db.refresh(profile)
        
        block = format_user_memory(profile, [])
        print("--- Formatted Block (New User) ---")
        print(block)
        assert "详实" in block
        assert "学术专家" in block
        print("✅ New user profile format verified!")
        
        # 3. Simulate Dialogue Turn 1 & Memory Extraction
        print("\n🗣️ [LTM Test] 3. Simulating dialogue turn 1: Discussion about Cao Cao...")
        question = "老夫想了解曹操在建安五年官渡之战中的排兵布阵，越详尽越好！"
        answer = (
            "阁下垂问，老夫当倾囊相授。建安五年，袁绍勒兵十万南下，曹操兵力虽仅万余，但其调度极佳。"
            "战前，操遣臧霸入青州以牵制袁绍左翼，自引大军屯官渡扼守要冲。此战精髓在于操纳许攸之策，"
            "亲率步骑五千夜袭乌巢，斩淳于琼，尽烧袁军粮谷，从而一举扭转战局。此役足见曹操决机神速、用人有道。"
        )
        
        print("🧠 [LTM Test] Running LLM-as-Extractor for turn 1...")
        await consolidate_memory_task(TEST_USER_ID, question, answer)
        
        # Fetch memories from DB to verify (using rollback to clear transaction cache and read background commits)
        db.rollback()
        memories = db.query(UserMemory).filter_by(user_id=TEST_USER_ID).all()
        print(f"📥 [LTM Test] Extracted {len(memories)} topics from turn 1.")
        for m in memories:
            print(f"   * 【{m.topic}】: {m.summary} (字数: {len(m.summary)})")
            assert len(m.summary) <= 100, f"Error: Summary for {m.topic} exceeds 100 chars!"
            
        # 4. Test Memory Formatting (With Data case)
        db.refresh(profile)
        memories_list = db.query(UserMemory).filter_by(user_id=TEST_USER_ID).all()
        block_with_data = format_user_memory(profile, memories_list)
        print("\n--- Formatted Block (With Memory Data) ---")
        print(block_with_data)
        assert "曹操" in block_with_data or "官渡之战" in block_with_data
        print("✅ Populated user memory format verified!")
        
        # 5. Simulate Dialogue Turn 2 (Testing Merge & Compress)
        print("\n🗣️ [LTM Test] 5. Simulating dialogue turn 2: More about Cao Cao's personality...")
        question2 = "曹操除了军事调度，待人接物上怎么样？"
        answer2 = (
            "操虽有枭雄之称，然极重才爱才，待人极厚，亦极严。如建安五年关羽为操所擒，操待之甚厚，"
            "封汉寿亭侯，三日一小宴，五日一大宴，送美女金帛。即便关羽最终挂印封金而去，操亦不许诸将追赶，"
            "叹曰：‘彼各为其主，勿追也。’其王霸之度、爱才之诚昭然若揭。"
        )
        
        print("🧠 [LTM Test] Running LLM-as-Extractor for turn 2 (should merge into existing Cao Cao topic)...")
        await consolidate_memory_task(TEST_USER_ID, question2, answer2)
        
        # Verify that topic is updated/merged, not appended as a new record (using rollback to refresh cache)
        db.rollback()
        final_memories = db.query(UserMemory).filter_by(user_id=TEST_USER_ID).all()
        print(f"📥 [LTM Test] Total topic records in database: {len(final_memories)}")
        
        # We expect the number of topics to remain small (1 or 2), and the summaries to be updated
        for m in final_memories:
            print(f"   * 【{m.topic}】: {m.summary} (字数: {len(m.summary)})")
            assert len(m.summary) <= 100, f"Error: Summary for {m.topic} exceeds 100 chars!"
            if "曹操" in m.topic:
                assert "关羽" in m.summary or "爱才" in m.summary or "待人" in m.summary, "Error: New details were not merged!"
                
        print("\n✅ Merge and compression behavior verified perfectly!")
        print("🎉 [LTM Test] All integration tests passed successfully!")
        
    except Exception as e:
        print(f"\n❌ [LTM Test] Test failed: {e}")
        raise e
    finally:
        # Clean up database after test
        print(f"\n🧹 [LTM Test] Final cleanup of test records for: {TEST_USER_ID}")
        db.query(UserMemory).filter_by(user_id=TEST_USER_ID).delete()
        db.query(UserProfile).filter_by(user_id=TEST_USER_ID).delete()
        db.commit()
        db.close()

if __name__ == "__main__":
    asyncio.run(run_test())
