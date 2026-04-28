import os
import json
import glob
from tqdm import tqdm
import chromadb
from chromadb.utils import embedding_functions

def build_vector_db():
    raw_data_dir = os.path.join("data", "raw")
    chroma_db_dir = os.path.join("data", "chroma_db")
    
    # 确保目录存在
    os.makedirs(chroma_db_dir, exist_ok=True)
    
    # 初始化 ChromaDB 客户端
    client = chromadb.PersistentClient(path=chroma_db_dir)
    
    # 使用 BGE 中文模型进行向量化 (会自动下载模型)
    # 注意：运行前需要 pip install sentence-transformers chromadb
    print("正在加载 BGE 向量模型...")
    sentence_transformer_ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="BAAI/bge-large-zh-v1.5")
    
    # 获取或创建 collection
    collection = client.get_or_create_collection(
        name="sanguozhi_events",
        embedding_function=sentence_transformer_ef,
        metadata={"hnsw:space": "cosine"} # 使用余弦相似度
    )
    
    json_files = glob.glob(os.path.join(raw_data_dir, "*.json"))
    
    docs = []
    metadatas = []
    ids = []
    
    print(f"开始解析 {len(json_files)} 个 JSON 文件...")
    for file_path in tqdm(json_files):
        filename = os.path.basename(file_path)
        person_name = filename.replace("_events.json", "")
        
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                events = json.load(f)
            except json.JSONDecodeError:
                print(f"Error reading {file_path}")
                continue
            
            for idx, event in enumerate(events):
                title = event.get("事件标题", "")
                summary = event.get("事件简介", "")
                original_text = event.get("原文", "")
                
                # 拼接文本作为输入向量的 Document
                document = f"标题：{title}\n简介：{summary}\n原文：{original_text}"
                
                # 提取 MetaData
                metadata = {
                    "source_file": filename,
                    "person_name": person_name,
                    "title": title,
                    "type": event.get("事件类型", "不详"),
                    "location": event.get("地点", "不详"),
                    # chroma 不支持 None，替换为 -1
                    "start_year": event.get("std_start_year") if event.get("std_start_year") is not None else -1, 
                    "end_year": event.get("std_end_year") if event.get("std_end_year") is not None else -1
                }
                
                # chroma 的 metadata 值必须是 str, int, float or bool
                for k, v in metadata.items():
                    if not isinstance(v, (str, int, float, bool)):
                        metadata[k] = str(v)
                
                doc_id = f"{person_name}_event_{idx}"
                
                docs.append(document)
                metadatas.append(metadata)
                ids.append(doc_id)
                
    # 批量写入 (Batch upsert)
    # Chroma 建议分批插入（例如每次 5000 条），防止内存溢出
    batch_size = 5000
    print(f"\n开始写入 ChromaDB，共 {len(docs)} 条记录...")
    
    for i in tqdm(range(0, len(docs), batch_size)):
        batch_docs = docs[i:i + batch_size]
        batch_metas = metadatas[i:i + batch_size]
        batch_ids = ids[i:i + batch_size]
        
        collection.upsert(
            documents=batch_docs,
            metadatas=batch_metas,
            ids=batch_ids
        )
        
    print("写入完成！库已保存在 data/chroma_db 目录。")

if __name__ == "__main__":
    build_vector_db()

    # 简单测试验证一下
    print("\n--- 测试检索 ---")
    client = chromadb.PersistentClient(path=os.path.join("data", "chroma_db"))
    sentence_transformer_ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="BAAI/bge-large-zh-v1.5")
    collection = client.get_collection(name="sanguozhi_events", embedding_function=sentence_transformer_ef)
    
    query = "诸葛亮北伐中原，六出祁山"
    results = collection.query(
        query_texts=[query],
        n_results=3
    )
    
    print(f"\n查询: '{query}'")
    for i, (doc, meta) in enumerate(zip(results['documents'][0], results['metadatas'][0])):
        print(f"\n[Result {i+1}] {meta['person_name']} - {meta['title']}")
        print(f"内容: {doc[:80]}...")
