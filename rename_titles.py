import os
import json
import glob

def rename_event_titles():
    # 获取 data/raw/ 下所有的 JSON 文件
    raw_files = glob.glob('data/raw/*.json')
    
    print(f"正在处理 {len(raw_files)} 个文件...")

    for filepath in raw_files:
        filename = os.path.basename(filepath)
        # 获取人名，例如从 "曹昂_events.json" 提取 "曹昂"
        person_name = filename.split('_')[0]
        
        with open(filepath, 'r', encoding='utf-8') as f:
            try:
                events = json.load(f)
            except Exception as e:
                print(f"读取文件失败 {filename}: {e}")
                continue
        
        modified = False
        for event in events:
            # 找到标题字段
            title_key = '事件标题' if '事件标题' in event else ('title' if 'title' in event else None)
            
            if title_key:
                old_title = event[title_key]
                # 如果旧标题里还不包含这个人名，则添加前缀
                if person_name not in old_title:
                    event[title_key] = f"{person_name}{old_title}"
                    modified = True
        
        if modified:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(events, f, ensure_ascii=False, indent=2)
            print(f"✅ 已更新文件: {filename} (前缀: {person_name})")

if __name__ == "__main__":
    rename_event_titles()
