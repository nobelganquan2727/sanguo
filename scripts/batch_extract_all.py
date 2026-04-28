import os
import glob
import shutil
from extract_events_llm import extract_events_from_text

def batch_process():
    root_dir = "sgraw"
    output_dir = "data/raw"
    backup_dir = "sgraw_backup"
    
    os.makedirs(backup_dir, exist_ok=True)
    
    
    # 获取魏蜀吴所有的 txt 文件
    all_files = []
    for kingdom in ['wei', 'shu', 'wu']:
        # 加上 recursive=True 防止目录结构有变，不过正常 glob 这样就能拿到
        files = glob.glob(os.path.join(root_dir, kingdom, "*.txt"))
        all_files.extend(files)
        
    print(f"📦 发现总任务数：{len(all_files)} 个传记文件")
    
    failed_files = []
    
    for i, file_path in enumerate(all_files, 1):
        print(f"\n=======================================================")
        print(f"🚀 正在处理第 {i}/{len(all_files)} 个文件: {file_path}")
        print(f"=======================================================")
        
        try:
            # 调用我们在 extract_events_llm.py 里的函数
            # 它内部已经实现了：探测传主 -> 分批请求 -> 生成独立的 JSON
            success = extract_events_from_text(input_file=file_path, output_dir=output_dir)
            
            if success:
                # 移动到 backup 文件夹中，保留相对路径目录结构（可选），或者直接扔进去
                base_name = os.path.basename(file_path)
                backup_path = os.path.join(backup_dir, base_name)
                shutil.move(file_path, backup_path)
                print(f"📁 已提取完毕，原文归档至：{backup_path}")
            else:
                print(f"⚠️ 文件提取未生成任何有效数据或遭遇失败：{file_path}")
                failed_files.append(file_path)
                
        except Exception as e:
            print(f"❌ 运行该文件时遭遇完全异常: {e}")
            failed_files.append(file_path)
    
    print("\n\n🎉 批量处理流程结束！")
    
    if failed_files:
        fail_log = os.path.join(output_dir, "failed_files.txt")
        print(f"⚠️ 有 {len(failed_files)} 个文件处理失败，已写入日志：{fail_log}")
        with open(fail_log, "w", encoding="utf-8") as f:
            for ff in failed_files:
                f.write(ff + "\n")
        print("遇到 API 超时或截断是很正常的，你可以随时根据 failed_files.txt 重跑这些文件。")
    else:
        print("✅ 太完美了！所有传记全数通关通过，没有产生任何失败日志。")

if __name__ == "__main__":
    batch_process()
