import os
import sys
import json
import glob
import asyncio
from dotenv import load_dotenv

# Add project root to sys.path to allow imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.extract_events import refine_missed_text_with_llm, load_context_data

load_dotenv()

async def refine_file_omissions(file_path: str, context_str: str):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            events = json.load(f)
    except Exception as e:
        print(f"❌ Failed to read {file_path}: {e}")
        return
        
    has_omission = False
    new_events = []
    
    # Extract biography owner from filename (e.g. "刘巴_events.json" -> "刘巴")
    base_name = os.path.basename(file_path).replace("_events.json", "")
    parts = base_name.split()
    biography_owner = parts[-1] if parts else "未知"
    
    for e in events:
        if e.get("事件标题") == "补充遗漏文本":
            has_omission = True
            missed_text = e.get("原文")
            print(f"🔍 Refining omission in {base_name}: '{missed_text}'")
            try:
                refined = await refine_missed_text_with_llm(missed_text, biography_owner, context_str)
                # Ensure the refined events have standard fields
                for rev in refined:
                    new_events.append(rev)
            except Exception as ex:
                print(f"  ❌ Error refining event: {ex}")
                new_events.append(e) # Keep original if fails
        else:
            new_events.append(e)
            
    if has_omission:
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(new_events, f, ensure_ascii=False, indent=2)
            print(f"✅ Updated {file_path} with refined events.")
        except Exception as e:
            print(f"❌ Failed to write {file_path}: {e}")

async def main():
    print("Loading context data from dictionary...")
    context_str = load_context_data()
    
    raw_files = sorted(glob.glob("data/raw/*_events.json"))
    print(f"Scanning {len(raw_files)} raw JSON files for omissions...")
    
    tasks = []
    for fpath in raw_files:
        tasks.append(refine_file_omissions(fpath, context_str))
        
    await asyncio.gather(*tasks)
    print("🎉 Finished refining all omissions!")

if __name__ == "__main__":
    asyncio.run(main())
