#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量修复三国人物事件JSON中的时间、地点和std_start_year字段。
基于事件简介和标题中的历史线索进行推断。
"""

import json
import glob
import re
import os

# 年号到起始年份的映射
ERA_START = {
    '中平': 184, '初平': 190, '兴平': 194, '建安': 196,
    '黄初': 220, '太和': 227, '青龙': 233, '景初': 237,
    '正始': 240, '嘉平': 249, '正元': 254, '甘露': 256,
    '景元': 260, '咸熙': 264,
    '黄武': 222, '黄龙': 229, '嘉禾': 232, '赤乌': 238,
    '太元': 251, '神凤': 252, '建兴': 252, '五凤': 254,
    '太平': 256, '永安': 258, '元兴': 264, '甘露吴': 265,
    '宝鼎': 266, '建衡': 269, '凤凰': 272, '天册': 275,
    '天玺': 276, '天纪': 277,
    '章武': 221, '建兴蜀': 223, '延熙': 238, '景耀': 258, '炎兴': 263,
    '熹平': 172, '光和': 178, '永汉': 189, '延康': 220,
    '绍汉': 221,  # 刘备
}

# 常见地点关键词（用于从简介中提取）
COMMON_PLACES = [
    '长安', '洛阳', '许都', '许昌', '邺城', '邺', '成都', '汉中', '荆州', '徐州',
    '扬州', '兖州', '豫州', '青州', '冀州', '并州', '凉州', '益州', '幽州', '交州',
    '江东', '吴地', '吴郡', '会稽', '丹阳', '丹杨', '豫章', '庐江', '江夏', '长沙',
    '桂阳', '零陵', '武陵', '南郡', '南阳', '江陵', '襄阳', '樊城', '新野', '公安',
    '武陵', '零陵', '长沙', '桂阳', '南郡', '江夏', '零陵', '桂阳',
    '合肥', '寿春', '下邳', '小沛', '彭城', '广陵', '东海', '琅邪', '泰山', '济南',
    '乐安', '北海', '东莱', '平原', '渤海', '河间', '清河', '赵国', '常山', '中山',
    '安平', '巨鹿', '广平', '魏郡', '赵国', '代郡', '上谷', '渔阳', '右北平', '辽西',
    '辽东', '玄菟', '乐浪', '带方', '高句骊', '乌丸', '鲜卑', '匈奴', '羌',
    '武威', '张掖', '酒泉', '敦煌', '西平', '金城', '陇西', '天水', '安定', '北地',
    '武都', '汉中', '巴郡', '广汉', '蜀郡', '犍为', '越巂', '牂牁', '益州', '永昌',
    '郡', '县', '城', '关', '亭', '陂', '津', '口', '山', '水', '江', '河', '陵',
]


def parse_year_from_text(text):
    """从文本中提取年份信息"""
    if not text:
        return None, None, False

    # 匹配 "建安五年（200年）"
    m = re.search(r'(中平|初平|兴平|建安|黄初|太和|青龙|景初|正始|嘉平|正元|甘露|景元|咸熙|黄武|黄龙|嘉禾|赤乌|太元|神凤|建兴|五凤|太平|永安|元兴|宝鼎|建衡|凤凰|天册|天玺|天纪|章武|延熙|景耀|炎兴|熹平|光和|永汉|延康)[，、]?\s*(\d+)[年]?[（\(]?(\d+)?[年]?[）\)]?', text)
    if m:
        era = m.group(1)
        year_num = int(m.group(2))
        explicit_year = m.group(3)
        if explicit_year:
            return int(explicit_year), f"{era}{year_num}年（{explicit_year}年）", False
        start = ERA_START.get(era)
        if start:
            year = start + year_num - 1
            return year, f"{era}{year_num}年（{year}年）", False

    # 匹配 "200年"
    m = re.search(r'(\d{3})[年]?', text)
    if m:
        year = int(m.group(1))
        if 150 <= year <= 280:
            return year, f"{year}年", False

    # 匹配 "灵帝末"
    if '灵帝末' in text or '灵帝末年' in text:
        return 188, "灵帝末年（188年左右）", True

    # 匹配 "中平年间"
    if '中平' in text:
        return 184, "中平年间（184年左右）", True

    # 匹配 "初平年间"
    if '初平' in text:
        return 190, "初平年间（190年左右）", True

    # 匹配 "兴平年间"
    if '兴平' in text:
        return 194, "兴平年间（194年左右）", True

    # 匹配 "建安年间"
    if '建安年间' in text or '建安中' in text:
        return 200, "建安年间（200年左右）", True

    # 匹配 "黄初年间"
    if '黄初' in text and '年间' in text:
        return 220, "黄初年间（220年左右）", True

    # 匹配 "明帝时期"
    if '明帝时期' in text or '明帝时' in text:
        return 226, "明帝时期（226年左右）", True

    # 匹配 "曹丕为太子时"
    if '曹丕为太子' in text or '太子' in text and '曹丕' in text:
        return 217, "曹丕为太子时（217-220年）", True

    # 匹配 "魏国建立'
    if '魏国建立' in text or '魏国初建' in text or '魏王国建立' in text:
        return 213, "魏国初建（213年）", True

    # 匹配 "赤壁之战"
    if '赤壁' in text:
        return 208, "建安十三年（208年）", False

    # 匹配 "官渡之战"
    if '官渡' in text:
        return 200, "建安五年（200年）", False

    return None, None, False


def infer_location_from_text(text, title):
    """从文本和标题中提取地点信息"""
    if not text:
        return None

    # 优先从标题中提取地点关键词
    locs = []

    # 常见地点模式
    place_patterns = [
        r'([^，。、]{1,6}郡)', r'([^，。、]{1,6}县)', r'([^，。、]{1,6}城)',
        r'([^，。、]{1,6}州)', r'([^，。、]{1,6}关)', r'([^，。、]{1,6}陵)',
        r'([^，。、]{1,6}阳)', r'([^，。、]{1,6}阴)', r'([^，。、]{1,6}津)',
        r'([^，。、]{1,6}口)', r'([^，。、]{1,6}山)', r'([^，。、]{1,6}水)',
        r'([^，。、]{1,6}江)', r'([^，。、]{1,6}河)', r'([^，。、]{1,6}陂)',
        r'([^，。、]{1,6}亭)', r'([^，。、]{1,6}陂)', r'([^，。、]{1,6}原)',
        r'([^，。、]{1,6}野)', r'([^，。、]{1,6}丘)', r'([^，。、]{1,6}阿)',
    ]

    # 从标题中提取
    for pat in place_patterns:
        ms = re.findall(pat, title)
        for m in ms:
            if len(m) >= 2 and m not in ['大将', '将军', '太守', '刺史', '司马', '都督', '校尉', '都尉', '中郎将', '侍郎', '尚书', '侍中', '郎中', '从事', '主簿', '功曹', '县令', '县长', '国相', '都守']:
                locs.append(m)

    # 从正文中提取明确的地点（前面有"在"、"于"、"至"、"屯"、"驻"、"守"、"攻"、"战"等动词）
    text_locs = re.findall(r'[在于至屯驻守攻战袭据奔走逃还入出到往过经渡临徙居于向趋赴](?:了|至|往|于|在|到)?[往于在至到]?([^，。、；\n]{1,6}郡|[^，。、；\n]{1,6}县|[^，。、；\n]{1,6}城|[^，。、；\n]{1,6}州|[^，。、；\n]{1,6}关|[^，。、；\n]{1,6}陵|[^，。、；\n]{1,6}阳|[^，。、；\n]{1,6}津|[^，。、；\n]{1,6}口|[^，。、；\n]{1,6}山|[^，。、；\n]{1,6}水|[^，。、；\n]{1,6}江|[^，。、；\n]{1,6}河|[^，。、；\n]{1,6}陂|[^，。、；\n]{1,6}亭|[^，。、；\n]{1,6}原|[^，。、；\n]{1,6}野|[^，。、；\n]{1,6}丘|[^，。、；\n]{1,6}阿)', text)
    for loc in text_locs:
        if len(loc) >= 2 and loc not in locs:
            # 过滤掉官职名
            if loc not in ['大将', '将军', '太守', '刺史', '司马', '都督', '校尉', '都尉', '中郎将', '侍郎', '尚书', '侍中', '郎中', '从事', '主簿', '功曹', '县令', '县长', '国相', '都守']:
                locs.append(loc)

    if locs:
        # 去重并保持顺序
        seen = set()
        result = []
        for loc in locs:
            if loc not in seen:
                seen.add(loc)
                result.append(loc)
        return '、'.join(result[:5])  # 最多5个地点

    return None


def infer_time_location(event):
    """推断单个事件的时间和地点"""
    title = event.get('事件标题', '')
    brief = event.get('事件简介', '')
    text = title + '。' + brief

    inferred_time = None
    inferred_std_year = None
    inferred_loc = None
    is_fuzzy = False

    # 推断时间
    year, time_str, fuzzy = parse_year_from_text(text)
    if year:
        inferred_std_year = year
        inferred_time = time_str
        is_fuzzy = fuzzy

    # 推断地点
    loc = infer_location_from_text(brief, title)
    if loc:
        inferred_loc = loc

    return inferred_time, inferred_std_year, inferred_loc, is_fuzzy


def main():
    files = sorted(glob.glob('*_events.json'))
    total_fixed = 0
    total_checked = 0
    manual_review = []

    for f in files:
        try:
            with open(f, 'r', encoding='utf-8') as fp:
                events = json.load(fp)
        except Exception as e:
            print(f"跳过损坏文件 {f}: {e}")
            continue

        modified = False
        for i, ev in enumerate(events):
            t = ev.get('时间', '')
            l = ev.get('地点', '')
            s = ev.get('std_start_year')
            needs_fix = (t == '不详') or (l == '不详') or (s is None)
            if not needs_fix:
                continue

            total_checked += 1
            new_time, new_year, new_loc, fuzzy = infer_time_location(ev)

            changes = []

            if t == '不详' and new_time:
                ev['时间'] = new_time
                changes.append(f"时间: {new_time}")

            if s is None and new_year:
                ev['std_start_year'] = new_year
                changes.append(f"std_start: {new_year}")
                if fuzzy:
                    ev['is_time_fuzzy'] = True

            if l == '不详' and new_loc:
                ev['地点'] = new_loc
                changes.append(f"地点: {new_loc}")

            if changes:
                total_fixed += 1
                modified = True
            else:
                # 记录需要手动审查的
                manual_review.append({
                    'file': f,
                    'idx': i,
                    'title': ev.get('事件标题', ''),
                    'time': t,
                    'loc': l,
                    'std': s,
                    'brief': ev.get('事件简介', '')[:100]
                })

        if modified:
            with open(f, 'w', encoding='utf-8') as fp:
                json.dump(events, fp, ensure_ascii=False, indent=2)

    print(f"检查了 {total_checked} 条记录")
    print(f"自动修复了 {total_fixed} 条记录")
    print(f"仍有 {len(manual_review)} 条需要手动审查")

    if manual_review:
        with open('/tmp/manual_review.txt', 'w', encoding='utf-8') as fp:
            for r in manual_review:
                fp.write(f"[{r['file']}] idx={r['idx']} | {r['title']}\n")
                fp.write(f"  时间={r['time']} 地点={r['loc']} std_start={r['std']}\n")
                fp.write(f"  简介: {r['brief']}\n\n")
        print(f"手动审查列表已保存到 /tmp/manual_review.txt")


if __name__ == '__main__':
    main()
