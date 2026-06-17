import json
import glob
import os

def calculate_chars():
    raw_files = glob.glob("data/raw/*_events.json")
    total_events = 0
    total_chars = 0
    
    for r_file in raw_files:
        with open(r_file, 'r', encoding='utf-8') as f:
            events = json.load(f)
        for e in events:
            total_events += 1
            title = e.get("事件标题", "")
            desc = e.get("事件简介", "") or e.get("事件翻译", "")
            text_to_embed = f"事件：{title}\n简介：{desc}"
            total_chars += len(text_to_embed)
            
    print(f"Total events: {total_events}")
    print(f"Total characters: {total_chars}")
    # Estimate tokens: for BGE-M3 (Chinese-English mixed), 1 character is roughly 1-1.5 tokens. Let's estimate 1.2 tokens per character.
    est_tokens = int(total_chars * 1.2)
    print(f"Estimated BGE-M3 tokens: {est_tokens}")

if __name__ == "__main__":
    calculate_chars()
