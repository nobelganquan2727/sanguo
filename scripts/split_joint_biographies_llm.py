import os
import sys
import json
import glob
import re
import asyncio
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

load_dotenv()

# Initialize LLM
api_key = os.environ.get("DEEPSEEK_API_KEY", "")
llm = ChatOpenAI(
    model="deepseek-chat", 
    api_key=api_key, 
    base_url="https://api.deepseek.com/v1",
    max_tokens=2048,
    temperature=0.1,
    model_kwargs={"response_format": {"type": "json_object"}}
)

# Normalize names for consistency
def normalize(name):
    n = name.strip()
    n = n.split('（')[0].split('(')[0]
    n = n.replace('锺', '钟').replace('叡', '睿')
    if n.startswith('先主'): n = n[2:]
    if n.startswith('后主'): n = n[2:]
    if n.startswith('武宣'): n = n[2:]
    if n.startswith('文德'): n = n[2:]
    if n.startswith('文昭'): n = n[2:]
    if n.startswith('明元'): n = n[2:]
    if n.startswith('明悼'): n = n[2:]
    if n.startswith('孙破虏'): n = n[3:]
    return n

async def split_file_with_llm(book_path: str, names: list):
    book_name = os.path.basename(book_path)
    print(f"\n📖 [LLM Splitting] Processing {book_name} for characters: {names}")
    
    with open(book_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        
    paragraphs = content.split('\n')
    headers = []
    for idx, p in enumerate(paragraphs):
        p_strip = p.strip()
        if p_strip:
            headers.append(f"{idx}: {p_strip[:50]}")
            
    headers_str = "\n".join(headers)
    
    system_prompt = """You are an expert historian specializing in Sanguozhi. 
We have a joint biography text split into paragraphs.
For the specified list of historical characters, you must identify their biography's paragraph range (start_index to end_index, inclusive).
You must output a JSON object where each character name maps to a list [start_index, end_index].
Format:
{
  "CharacterName1": [start_index, end_index],
  "CharacterName2": [start_index, end_index]
}
Ensure the end_index is the last paragraph of that character's biography (usually right before the next character's biography starts, or before '评曰' if it's the last character).
Return ONLY the raw JSON object.
"""
    user_prompt = f"""[Characters to extract]: {names}

[Paragraph headers (index: snippet)]:
{headers_str}
"""
    try:
        messages = [
            ("system", system_prompt),
            ("user", user_prompt)
        ]
        response = await llm.ainvoke(messages)
        res_json = json.loads(response.content.strip())
        
        # Slices paragraphs and write to data/raw_book/NAME.md
        os.makedirs("data/raw_book", exist_ok=True)
        
        for name, range_list in res_json.items():
            if not isinstance(range_list, list) or len(range_list) < 2:
                print(f"  ⚠️ Invalid range for {name}: {range_list}")
                continue
            start, end = range_list[0], range_list[1]
            if start < 0 or end >= len(paragraphs) or start > end:
                print(f"  ⚠️ Out of bounds range for {name}: [{start}, {end}]")
                continue
                
            char_text = "\n".join(paragraphs[start:end+1]).strip()
            # Prefix with title
            md_content = f"# {name}\n\n{char_text}\n"
            
            # Save file
            out_file = f"data/raw_book/{name}.md"
            with open(out_file, 'w', encoding='utf-8') as out_f:
                out_f.write(md_content)
            print(f"  ✅ Saved data/raw_book/{name}.md (paragraphs {start}-{end}, {len(char_text)} chars)")
            
    except Exception as e:
        print(f"  ❌ Error splitting {book_name} with LLM: {e}")

HARDCODED_MAPPINGS = {
    # 曹魏世子及宗室等难定位人物
    "曹昂": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹冲": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹宇": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹林": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹舆": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹均": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹徽": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹茂": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹矩": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹干": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹幹": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹子上": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹彪": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹蕤": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹邕": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹贡": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹俨": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹子乘": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹整": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹子京": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹棘": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹子棘": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹协": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹鉴": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹霖": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹礼": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹子勤": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹温": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹迈": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹阐": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹峻": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹据": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹熙": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹衮": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹赞": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹传": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹作": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹铄": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹玹": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "曹彪": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    "相殇王铄": "三国志_卷二十 魏书二十 武文世王公传第二十.txt",
    
    # 蜀汉嫔妃及皇子
    "刘璿": "三国志_卷三十四 蜀书四 二主妃子传第四.txt",
    "先主穆皇后": "三国志_卷三十四 蜀书四 二主妃子传第四.txt",
    "穆皇后": "三国志_卷三十四 蜀书四 二主妃子传第四.txt",
    "敬哀皇后": "三国志_卷三十四 蜀书四 二主妃子传第四.txt",
    "张皇后": "三国志_卷三十四 蜀书四 二主妃子传第四.txt",
    
    # 其它漏拆的大臣
    "孙邻": "三国志_卷五十一 吴书六 宗室传第六.txt",
    "孙瑜": "三国志_卷五十四 吴书九 周瑜鲁肃吕蒙传第九.txt",
    "庞德": "三国志_卷十八 魏书十八 二李臧文吕许典二庞阎传第十八.txt",
    "廖化": "三国志_卷四十五 蜀书十五 邓张宗杨传第十五.txt",
    "董昭": "三国志_卷十四 魏书十四 程郭董刘蒋刘传第十四.txt",
    "张邈": "三国志_卷七 魏书七 吕布张邈臧洪传第七.txt",
    "张杨": "三国志_卷八 魏书八 二公孙陶四张传第八.txt",
    "张燕": "三国志_卷八 魏书八 二公孙陶四张传第八.txt",
    "张绣": "三国志_卷八 魏书八 二公孙陶四张传第八.txt",
    "张鲁": "三国志_卷八 魏书八 二公孙陶四张传第八.txt",
    "公孙度": "三国志_卷八 魏书八 二公孙陶四张传第八.txt",
    "李典": "三国志_卷十八 魏书十八 二李臧文吕许典二庞阎传第十八.txt",
    "辛毗": "三国志_卷二十五 辛毗杨阜高堂隆传第二十五.txt",
    "陶谦": "三国志_卷八 魏书八 二公孙陶四张传第八.txt"
}

async def main():
    # Load 331 names from metadata
    with open('data/character_static_metadata.json', 'r', encoding='utf-8') as f:
        meta = json.load(f)
    meta_names = set(item.get('name') for item in meta if item.get('name'))
    
    # Get names already in data/raw/ or data/raw_book/
    raw_files = glob.glob('data/raw/*_events.json')
    raw_names = set(os.path.basename(f).replace('_events.json', '') for f in raw_files)
    
    missing = sorted([name for name in meta_names if normalize(name) not in {normalize(rn) for rn in raw_names}])
    print(f"Total actual missing characters: {len(missing)}")
    
    if not missing:
        print("🎉 No missing characters found!")
        return
        
    # Map missing names to original book texts
    book_files = sorted(glob.glob('../Sanguo/raw/*.txt'))
    book_texts = {}
    for bf in book_files:
        with open(bf, 'r', encoding='utf-8', errors='ignore') as f:
            book_texts[os.path.basename(bf)] = f.read()
            
    mapping = {}
    for name in missing:
        # 1. 优先使用 Hardcoded 映射规则
        clean_name = name.split('（')[0].split('(')[0]
        if clean_name in HARDCODED_MAPPINGS:
            mapping.setdefault(HARDCODED_MAPPINGS[clean_name], []).append(name)
            continue
            
        search_name = clean_name
        if search_name == '先主穆皇后': search_name = '穆皇后'
        if search_name == '敬哀皇后': search_name = '敬哀'
        if search_name == '张皇后': search_name = '张氏'
        if search_name == '锺繇': search_name = '钟繇'
        
        matched_books = []
        for bf_name, text in book_texts.items():
            if search_name in text:
                count = text.count(search_name)
                matched_books.append((bf_name, count))
                
        if matched_books:
            matched_books.sort(key=lambda x: x[1], reverse=True)
            best_book = matched_books[0][0]
            mapping.setdefault(best_book, []).append(name)
        else:
            mapping.setdefault('unknown', []).append(name)
            
    # Process each book that contains missing names
    tasks = []
    for bf_name, names in mapping.items():
        if bf_name == 'unknown':
            print(f"⚠️ Cannot map these names to any raw text: {names}")
            continue
            
        book_path = os.path.join("../Sanguo/raw", bf_name)
        tasks.append(split_file_with_llm(book_path, names))
        
    await asyncio.gather(*tasks)
    print("\n🎉 Joint biographies splitting complete!")

if __name__ == '__main__':
    asyncio.run(main())
