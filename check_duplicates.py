import os
import json
import glob
from collections import defaultdict

def check_duplicate_titles():
    # 获取 data/raw/ 下所有的 JSON 文件
    raw_files = glob.glob('data/raw/*.json')
    title_map = defaultdict(list)
    
    print(f"正在扫描 {len(raw_files)} 个文件...")

    for filepath in raw_files:
        filename = os.path.basename(filepath)
        with open(filepath, 'r', encoding='utf-8') as f:
            try:
                events = json.load(f)
            except Exception as e:
                print(f"解析文件失败 {filename}: {e}")
                continue
            
            for event in events:
                # 获取标题（兼容“事件标题”和“title”）
                title = event.get('事件标题') or event.get('title')
                if title:
                    title_map[title].append(filename)

    # 找出重名的标题
    duplicates = {title: files for title, files in title_map.items() if len(files) > 1}

    if not duplicates:
        print("\n✅ 扫描完成：未发现重名的事件标题。")
    else:
        print(f"\n❌ 发现 {len(duplicates)} 组重名标题：")
        print("-" * 50)
        # 按重名次数降序排列
        for title in sorted(duplicates, key=lambda x: len(duplicates[x]), reverse=True):
            files = duplicates[title]
            print(f"标题: 【{title}】 (出现 {len(files)} 次)")
            print(f"出现在以下文件: {', '.join(files)}")
            print("-" * 50)

if __name__ == "__main__":
    check_duplicate_titles()
