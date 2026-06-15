import asyncio
import sys
import os
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.tools import get_person_timeline_async

async def main():
    print("Executing get_person_timeline_async for 诸葛亮...")
    results = await get_person_timeline_async.ainvoke({"name": "诸葛亮", "start_year": 227, "end_year": 229})
    print(f"Results length: {len(results)}")
    print("Result preview:")
    print(results[:1000])
    
    # Try parsing it
    try:
        parsed = json.loads(results)
        print("Success parsing locally!")
        print("Data:")
        print(json.dumps(parsed, indent=2, ensure_ascii=False))
    except Exception as e:
        print("Failed parsing locally:", e)

if __name__ == "__main__":
    asyncio.run(main())
