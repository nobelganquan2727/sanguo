import glob
import json
import os

# 配置路径
INPUT_DIR = "data/raw"  # 原始JSON文件目录
MAPPING_FILE = "scripts/event_type_mapping.json"  # 映射文件
BACKUP_DIR = "data/backup"  # 备份目录，如果不需要备份设为None

# 1. 加载映射文件
with open(MAPPING_FILE, 'r', encoding='utf-8') as f:
    category_mapping = json.load(f)

# 2. 创建反向映射
reverse_mapping = {}
for main_category, sub_categories in category_mapping.items():
    for sub_category in sub_categories:
        reverse_mapping[sub_category] = main_category

# 3. 获取所有JSON文件
all_json_files = glob.glob(os.path.join(INPUT_DIR, "*_events.json"))

if not all_json_files:
    print(f"在 {INPUT_DIR} 中没有找到 *_events.json 文件")
    exit()

# 4. 可选：创建备份目录
if BACKUP_DIR and os.path.isdir(INPUT_DIR):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    import shutil

    for file_path in all_json_files:
        backup_path = os.path.join(BACKUP_DIR, os.path.basename(file_path))
        shutil.copy2(file_path, backup_path)
    print(f"已备份 {len(all_json_files)} 个文件到 {BACKUP_DIR}")

# 5. 处理文件
processed_count = 0
for file_path in all_json_files:
    # print(f"处理: {os.path.basename(file_path)}")

    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    updated_count = 0
    for event in data:
        if "事件类型" in event:
            original_type = event["事件类型"]

            if original_type in reverse_mapping:
                new_type = reverse_mapping[original_type]
                event["事件类型"] = new_type
                updated_count += 1
            else:
                # 未找到映射
                print(f"  ⚠️ 未映射: {original_type}")
                event["事件类型"] = "其他"

    # 6. 写回原文件
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # print(f"  ✅ 更新了 {updated_count} 个事件类型")
    processed_count += 1

print(f"\n✅ 处理完成！共更新了 {processed_count} 个文件")