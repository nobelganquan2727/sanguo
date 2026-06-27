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

# Chapter to character mappings for ALL joint biographies that we want to split
CHAPTER_CHARACTERS = {
    "三国志_卷八 魏书八 二公孙陶四张传第八.txt": ["公孙度", "陶谦", "张杨", "张燕", "张绣", "张鲁"],
    "三国志_卷十一 魏书十一 袁张凉国田王邴管传第十一.txt": ["管宁", "张范", "凉茂", "国渊", "田畴", "王脩", "邴原"],
    "三国志_卷十三 魏书十三 钟繇华歆王朗传第十三.txt": ["钟繇", "华歆", "王朗"],
    "三国志_卷十四 魏书十四 程郭董刘蒋刘传第十四.txt": ["刘晔", "蒋济", "郭嘉", "董昭", "程昱"],
    "三国志_卷十八 魏书十八 二李臧文吕许典二庞阎传第十八.txt": ["李典", "李通", "臧霸", "文聘", "吕虔", "许褚", "典韦", "庞德", "庞淯", "阎温"],
    "三国志_卷二十 魏书二十 武文世王公传第二十.txt": [
        "曹昂", "曹冲", "曹宇", "曹林", "曹舆", "曹均", "曹徽", "曹茂", "曹矩", "曹干", "曹幹",
        "曹子上", "曹彪", "曹蕤", "曹邕", "曹贡", "曹俨", "曹子乘", "曹整", "曹子京", "曹棘",
        "曹子棘", "曹协", "曹鉴", "曹霖", "曹礼", "曹子勤", "曹温", "曹迈", "曹阐", "曹峻",
        "曹据", "曹熙", "曹衮", "曹赞", "曹传", "曹作", "曹铄", "相殇王铄", "曹玹"
    ],
    "三国志_卷二十二 魏书二十二 桓二陈徐卫卢传第二十二.txt": ["桓阶", "陈群", "陈矫", "徐宣", "卫臻", "卢毓"],
    "三国志_卷三十四 蜀书四 二主妃子传第四.txt": ["甘皇后", "穆皇后", "敬哀皇后", "张皇后", "刘璿", "先主甘皇后", "先主穆皇后"],
    "三国志_卷五十 吴书五 妃嫔传第五.txt": ["吴夫人", "谢夫人", "徐夫人", "步夫人", "王夫人", "潘夫人", "孙破虏吴夫人"],
    "三国志_卷五十一 吴书六 宗室传第六.txt": ["孙静", "孙瑜", "孙皎", "孙奂", "孙贲", "孙辅", "孙翊", "孙匡", "孙韶", "孙桓", "孙邻"],
    "三国志_卷四十五 蜀书十五 邓张宗杨传第十五.txt": ["廖化"]
}

def parse_json_flexible(content: str) -> dict:
    try:
        return json.loads(content)
    except Exception:
        pass
    
    result = {}
    blocks = re.findall(r'"([^"]+)"\s*:\s*\{\s*"start_sentence"\s*:\s*"(.*?)"\s*,\s*"end_sentence"\s*:\s*"(.*?)"\s*\}', content, re.DOTALL)
    for name, start, end in blocks:
        result[name] = {"start_sentence": start.strip(), "end_sentence": end.strip()}
    return result

def find_text_robust(full_text: str, query_s: str, search_start_idx: int = 0) -> int:
    # Remove all non-Chinese characters to match strictly on Chinese character sequence
    clean_query = re.sub(r'[^\u4e00-\u9fff]', '', query_s)
    if not clean_query:
        return -1
        
    # Take the first 8-10 characters as the unique feature key
    feature_chars = clean_query[:8]
    
    # Construct regex allowing any non-Chinese character in between
    regex_pattern = "[^\u4e00-\u9fff]*".join(re.escape(c) for c in feature_chars)
    
    match = re.search(regex_pattern, full_text[search_start_idx:])
    if match:
        return search_start_idx + match.start()
    return -1

async def split_chapter(book_name: str, names: list):
    book_path = os.path.join("../Sanguo/raw", book_name)
    if not os.path.exists(book_path):
        print(f"⚠️ Book file not found: {book_path}")
        return
        
    print(f"\n📖 [LLM Sentence Splitting] Processing {book_name} for characters: {names}")
    
    with open(book_path, 'r', encoding='utf-8', errors='ignore') as f:
        full_text = f.read()
        
    system_prompt = """You are an expert historian. We have a Sanguozhi joint biography chapter text.
Please identify the exact starting sentence and the exact ending sentence of the biography section for each of the specified characters.

CRITICAL RULES:
1. Each start_sentence and end_sentence MUST be short (exactly 12 to 18 characters long).
2. DO NOT include any double quotes ("), brackets, or parenthetical annotations in start_sentence or end_sentence. 
3. If there is a quote or bracket in the text near the start/end, just start/end right after or before it. 
This is crucial to avoid JSON parsing and escaping errors!

Return a JSON object in this format:
{
  "CharacterName": {
    "start_sentence": "short exact start string (12-18 chars)",
    "end_sentence": "short exact end string (12-18 chars)"
  }
}
Return ONLY the raw JSON object.
"""
    
    user_prompt = f"""[Characters to extract]: {names}

[Biography Full Text]:
{full_text}
"""
    
    try:
        messages = [
            ("system", system_prompt),
            ("user", user_prompt)
        ]
        response = await llm.ainvoke(messages)
        res_content = response.content.strip()
        res_json = parse_json_flexible(res_content)
        
        if not res_json:
            print(f"  ❌ Failed to parse JSON even with regex fallback for {book_name}!")
            print(f"     Raw response:\n{res_content[:500]}...")
            return
            
        os.makedirs("data/raw_book", exist_ok=True)
        
        for name, boundaries in res_json.items():
            start_s = boundaries.get("start_sentence", "").strip()
            end_s = boundaries.get("end_sentence", "").strip()
            
            if not start_s or not end_s:
                print(f"  ⚠️ Missing start/end sentence for {name}")
                continue
                
            # Find start index in full text using robust matching
            start_idx = find_text_robust(full_text, start_s, 0)
            if start_idx == -1:
                # Try fallback on first 6 chars
                start_idx = find_text_robust(full_text, start_s[:6], 0)
                
            if start_idx == -1:
                print(f"  ❌ Failed to locate start index for {name}: '{start_s}'")
                continue
                
            # Find end index in full text STARTING FROM start_idx (essential for repetitive text!)
            end_idx = find_text_robust(full_text, end_s, start_idx)
            if end_idx == -1:
                # Try fallback on first 6 chars
                end_idx = find_text_robust(full_text, end_s[:6], start_idx)
                
            if end_idx == -1:
                print(f"  ❌ Failed to locate end index for {name}: '{end_s}' (searched after index {start_idx})")
                continue
                
            # Compute end boundary index
            # Try to match the end of the query string in original text or default to +15 chars
            end_match_idx = full_text.find(end_s, end_idx)
            if end_match_idx != -1:
                actual_end_idx = end_match_idx + len(end_s)
            else:
                actual_end_idx = end_idx + 15
            
            char_text = full_text[start_idx:actual_end_idx].strip()
            md_content = f"# {name}\n\n{char_text}\n"
            
            out_file = f"data/raw_book/{name}.md"
            with open(out_file, 'w', encoding='utf-8') as out_f:
                out_f.write(md_content)
            print(f"  ✅ Saved data/raw_book/{name}.md (Length: {len(char_text)} chars)")
            
    except Exception as e:
        print(f"  ❌ Error splitting {book_name} with LLM: {e}")

async def main():
    tasks = []
    for book_name, names in CHAPTER_CHARACTERS.items():
        tasks.append(split_chapter(book_name, names))
        
    await asyncio.gather(*tasks)
    print("\n🎉 Sentence-boundary splitting complete!")

if __name__ == '__main__':
    asyncio.run(main())
