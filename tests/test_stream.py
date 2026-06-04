import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.qa_agent import ask_question_stream

async def main():
    print("🚀 Testing ask_question_stream...")
    question = "刘备和曹操在煮酒论英雄之后有什么纠葛？"
    history = [
        {"role": "user", "content": "你好，曹操当时在哪？"},
        {"role": "assistant", "content": "曹操当时在许都。"}
    ]
    
    count = 0
    async for chunk in ask_question_stream(question, history):
        print(f"[{count}] {chunk.strip()}")
        count += 1
        
if __name__ == "__main__":
    asyncio.run(main())
