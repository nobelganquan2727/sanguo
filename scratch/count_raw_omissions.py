import glob
import json
import os

def count_omissions():
    raw_files = glob.glob("data/raw/*_events.json")
    total_omitted_events = 0
    total_events = 0
    
    for fpath in raw_files:
        with open(fpath, 'r', encoding='utf-8') as f:
            events = json.load(f)
        for e in events:
            total_events += 1
            if e.get("事件标题") == "补充遗漏文本":
                total_omitted_events += 1
                
    print(f"Total events in JSON: {total_events}")
    print(f"Total '补充遗漏文本' events in JSON: {total_omitted_events}")

if __name__ == "__main__":
    count_omissions()
