import asyncio
import sys
import os
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.qa_agent import QAStreamPipeline

async def test():
    question = "诸葛亮第一次北伐时，蜀汉和曹魏分别是如何派兵部署的？"
    queue = asyncio.Queue()
    pipeline = QAStreamPipeline(question, history=[], queue=queue, handler=None)
    await pipeline.execute_pipeline()
    
    for i, obs in enumerate(pipeline.all_observations):
        res_data = obs.get("result", "")
        print(f"\n[Observation {i+1}] length: {len(res_data)}")
        print(f"Ends with: {repr(res_data[-100:])}")

if __name__ == "__main__":
    asyncio.run(test())
