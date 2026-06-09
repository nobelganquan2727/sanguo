import json
import glob
import os
import hashlib
import re

def generate_id(text: str) -> str:
    return hashlib.md5(text.encode('utf-8')).hexdigest()[:8]

def normalize_text(text: str) -> str:
    text = text.replace("锺", "钟")
    # Remove all spaces, punctuation, quotes, newlines
    return re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]', '', text)

raw_files = glob.glob("data/raw/*_events.json")

# Map of normalized text to raw event ID
normalized_raw_map = {}
raw_events_map = {}
for r_file in raw_files:
    with open(r_file, 'r', encoding='utf-8') as f:
        events = json.load(f)
    for e in events:
        event_caption = e.get('事件简介', str(e))
        event_id = f"evt_{generate_id(event_caption)}"
        raw_events_map[event_id] = e
        normalized_raw_map[normalize_text(event_caption)] = event_id

print(f"Total raw events: {len(raw_events_map)}")

vector_files = glob.glob("data/vectors_bgem3/*_events.json")
matched_count = 0
total_vector_events = 0

for v_file in vector_files:
    with open(v_file, 'r', encoding='utf-8') as f:
        events = json.load(f)
    for e in events:
        total_vector_events += 1
        doc = e.get("document", "")
        # Try to extract the brief/description
        match = re.search(r'简介：(.*?)\n原文：', doc, re.DOTALL)
        if match:
            brief = match.group(1).strip()
            norm_brief = normalize_text(brief)
            if norm_brief in normalized_raw_map:
                matched_count += 1
            else:
                title = e.get("metadata", {}).get("title", "")
                print(f"Mismatch normalized: {repr(norm_brief)}")
                print(f"Vector Title: {title}")
                print("-" * 50)
        else:
            print("Could not parse description from document:", doc[:100])

print(f"Total vector events: {total_vector_events}")
print(f"Successfully matched: {matched_count} / {total_vector_events} ({matched_count/total_vector_events*100:.2f}%)")
