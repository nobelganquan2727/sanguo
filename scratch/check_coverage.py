import os
import json
import re
import glob

def check_file_coverage(txt_path, json_path):
    if not os.path.exists(txt_path) or not os.path.exists(json_path):
        return None

    # 读取原始文本并按自然段合并，去除段落前后的空白
    with open(txt_path, "r", encoding="utf-8") as f:
        text = f.read()
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    original_text = "".join(paragraphs)
    original_chars = re.sub(r'[^\u4e00-\u9fff]', '', original_text)

    # 读取 JSON 事件
    with open(json_path, "r", encoding="utf-8") as f:
        events = json.load(f)

    # 提取所有事件原文的纯文字
    extracted_text = "".join([ev.get("原文", "") for ev in events])
    extracted_chars = re.sub(r'[^\u4e00-\u9fff]', '', extracted_text)

    coverage = len(extracted_chars) / len(original_chars) * 100 if len(original_chars) > 0 else 0

    # 用切分句子的方法查找漏掉的片段
    sentences = re.split(r'([。；？！])', original_text)
    processed_sentences = []
    for i in range(0, len(sentences)-1, 2):
        s = sentences[i].strip() + sentences[i+1]
        if len(s) > 10:  # 忽略过短的分句
            processed_sentences.append(s)
            
    if len(sentences) % 2 != 0 and len(sentences[-1].strip()) > 10:
        processed_sentences.append(sentences[-1].strip())

    missed_segments = []
    for s in processed_sentences:
        s_clean = re.sub(r'[^\u4e00-\u9fff]', '', s)
        if not s_clean:
            continue
        if s_clean not in extracted_chars:
            missed_segments.append(s)

    return {
        "original_len": len(original_chars),
        "extracted_len": len(extracted_chars),
        "coverage": coverage,
        "num_events": len(events),
        "missed_count": len(missed_segments),
        "missed_examples": missed_segments
    }

def main():
    txt_dir = "data/raw_book"
    json_dir = "data/raw"
    
    txt_files = glob.glob(os.path.join(txt_dir, "*.txt"))
    if not txt_files:
        print(f"Error: No txt files found in {txt_dir}")
        return
        
    print(f"🔍 正在检查 {len(txt_files)} 个文件的覆盖率...")
    results = []
    
    for txt_path in txt_files:
        file_name = os.path.basename(txt_path)
        base_name = os.path.splitext(file_name)[0]
        json_path = os.path.join(json_dir, f"{base_name}_events.json")
        
        info = check_file_coverage(txt_path, json_path)
        if info:
            results.append((base_name, info))
        else:
            # 标记尚未提取的卷
            results.append((base_name, "Not Extracted"))
            
    # 按照覆盖率从低到高排序，已提取的排在前面，未提取的排在最后
    extracted_results = [r for r in results if isinstance(r[1], dict)]
    not_extracted_results = [r for r in results if not isinstance(r[1], dict)]
    
    extracted_results.sort(key=lambda x: x[1]["coverage"])
    
    print("\n==================================== 覆盖率对比报告 ====================================")
    print(f"{'文件名 (卷名)':<30} | {'原始字数':<6} | {'提取字数':<6} | {'覆盖率':<8} | {'唯一事件数':<5} | {'漏提段落':<5}")
    print("-" * 88)
    
    for name, info in extracted_results:
        # 截断过长文件名以美化表格
        display_name = name[:26] + "..." if len(name) > 28 else name
        print(f"{display_name:<30} | {info['original_len']:<8d} | {info['extracted_len']:<8d} | {info['coverage']:>7.2f}% | {info['num_events']:<10d} | {info['missed_count']:<5d}")
        
    if not_extracted_results:
        print("-" * 88)
        print(f"⚠️ 还有 {len(not_extracted_results)} 个文件尚未进行事件提取。")
        for name, _ in not_extracted_results[:10]:
            print(f"  - [未提取] {name}")
        if len(not_extracted_results) > 10:
            print(f"  ... 还有 {len(not_extracted_results) - 10} 个文件未列出。")
            
    print("========================================================================================\n")
    
    # 打印覆盖率异常（低于98%）的文件详细漏提情况
    low_coverage = [r for r in extracted_results if r[1]["coverage"] < 98.0]
    if low_coverage:
        print("⚠️ 警告：检测到以下文件覆盖率低于 98%，漏提细节如下：")
        for name, info in low_coverage:
            print(f"\n  👉 【{name}】覆盖率: {info['coverage']:.2f}%, 漏提共 {info['missed_count']} 处:")
            for idx, seg in enumerate(info["missed_examples"][:5]):
                print(f"    [{idx+1}] {seg}")
            if len(info["missed_examples"]) > 5:
                print(f"    ... 还有 {len(info['missed_examples']) - 5} 处未列出。")
    else:
        print("🎉 极好！所有已提取的文件覆盖率均在 98% 以上！")

if __name__ == "__main__":
    main()
