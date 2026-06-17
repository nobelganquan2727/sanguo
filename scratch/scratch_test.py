import asyncio
import sys
import os
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.qa_agent import QAStreamPipeline, extract_events_from_observations

async def test():
    question = "荀彧的四胜论 它的深度如何 它到底好在哪里"
    queue = asyncio.Queue()
    
    # We create the pipeline without a Langfuse handler to avoid sending trace data
    pipeline = QAStreamPipeline(question, history=[], queue=queue, handler=None)
    
    print("--- 1. Executing pipeline ---")
    q_type = await pipeline.execute_pipeline()
    print(f"Classification type: {q_type}")
    print(f"Rewritten question: {getattr(pipeline, 'rewritten_q', '')}")
    
    print("\n--- 2. Final response ---")
    final_ans = "".join(pipeline.collected_text)
    print(final_ans)
    
    print("\n--- 3. Raw Observations ---")
    for i, obs in enumerate(pipeline.all_observations):
        print(f"\n[Observation {i+1}] Tool: {obs['tool']} | Query: {obs['query']}")
        res = obs['result']
        print(f"Result length: {len(res)} bytes")
        # Try to print some preview
        try:
            parsed = json.loads(res)
            print("Parsed JSON count:", len(parsed) if isinstance(parsed, list) else 1)
            # Print titles
            if isinstance(parsed, list):
                for idx, item in enumerate(parsed[:5]):
                    print(f"  - Item {idx}: {item.get('title') or item.get('e.title')} ({item.get('locations') or item.get('location') or item.get('l.name')})")
            else:
                print("  - Item:", parsed.get('title'))
        except Exception:
            print("Preview:", res[:300])
            
    print("\n--- 4. Event Extraction & Relevance Calculation ---")
    rewritten_q = getattr(pipeline, "rewritten_q", question)
    
    # Let's inspect each item inside extract_events_from_observations
    from agent.qa_agent import get_containment_similarity, get_similarity
    
    extracted = []
    seen_titles = set()
    for obs in pipeline.all_observations:
        res_data = obs.get("result", "")
        if not res_data:
            continue
        try:
            # Match the trailer split logic in qa_agent.py
            if "\n\n【卷宗纪要说明】" in res_data:
                res_data = res_data.split("\n\n【卷宗纪要说明】")[0]
            
            parsed = json.loads(res_data)
            if not isinstance(parsed, list):
                parsed = [parsed]
            for item in parsed:
                title = item.get("title") or item.get("e.title")
                if not title:
                    continue
                if title in seen_titles:
                    continue
                seen_titles.add(title)
                
                ans_score = get_containment_similarity(title, final_ans)
                q_score = get_similarity(title, rewritten_q)
                relevance_score = ans_score * 0.7 + q_score * 0.3
                
                print(f"Event: {title} | ans_score: {ans_score:.3f} | q_score: {q_score:.3f} | relevance_score: {relevance_score:.3f}")
                if relevance_score >= 0.15:
                    extracted.append((title, relevance_score))
        except Exception as e:
            print(f"Error parsing item: {e}")
            
    print("\nFiltered Events (relevance >= 0.15):")
    for title, score in sorted(extracted, key=lambda x: x[1], reverse=True):
        print(f"  * {title} (score: {score:.3f})")

if __name__ == "__main__":
    asyncio.run(test())
