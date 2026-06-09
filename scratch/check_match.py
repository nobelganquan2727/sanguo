import json
import glob
import os

raw_files = sorted(glob.glob("data/raw/*_events.json"))
vector_files = sorted(glob.glob("data/vectors_bgem3/*_events.json"))

print(f"Raw files count: {len(raw_files)}")
print(f"Vector files count: {len(vector_files)}")

mismatches = 0
for r_file in raw_files:
    basename = os.path.basename(r_file)
    v_file = os.path.join("data/vectors_bgem3", basename)
    if not os.path.exists(v_file):
        print(f"Missing vector file for {basename}")
        mismatches += 1
        continue
        
    with open(r_file, 'r', encoding='utf-8') as f:
        raw_events = json.load(f)
    with open(v_file, 'r', encoding='utf-8') as f:
        vector_events = json.load(f)
        
    if len(raw_events) != len(vector_events):
        print(f"Mismatch in count for {basename}: raw={len(raw_events)}, vector={len(vector_events)}")
        mismatches += 1
        continue
        
    for i, (re, ve) in enumerate(zip(raw_events, vector_events)):
        raw_title = re.get("事件标题", "")
        vec_title = ve.get("metadata", {}).get("title", "")
        if raw_title != vec_title:
            print(f"Title mismatch in {basename} at index {i}: raw='{raw_title}', vec='{vec_title}'")
            mismatches += 1
            break

if mismatches == 0:
    print("All files and events matched perfectly!")
else:
    print(f"Found {mismatches} mismatches.")
