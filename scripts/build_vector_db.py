import os
# 解决 Mac GPU 内存上限引起的 OOM 报错：在 PyTorch 载入前自动解除 MPS 内存上限限制
os.environ["PYTORCH_MPS_HIGH_WATERMARK_RATIO"] = "0.0"

import json
import glob
import argparse
from tqdm import tqdm
import chromadb

# 自动从 .env 加载环境变量（如果还有其他非 embedding 相关的环境变量需要的话）
# 使用 __file__ 定位父目录下的 .env，确保无论在哪个路径运行脚本都能正确读取配置
_base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_env_path = os.path.join(_base_dir, ".env")
if os.path.exists(_env_path):
    with open(_env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

class LocalBgem3EmbeddingFunction(chromadb.EmbeddingFunction):
    """
    本地 BGE-M3 向量化类，集成在 Chroma 中。
    支持在检索时自动为查询文本生成向量。
    """
    def __init__(self, model_name: str = "BAAI/bge-m3"):
        self.model_name = model_name
        self.model = None
        
    def __call__(self, input: chromadb.Documents) -> chromadb.Embeddings:
        if self.model is None:
            from sentence_transformers import SentenceTransformer
            print(f"正在延迟加载本地 BGE-M3 向量模型 ({self.model_name})...")
            self.model = SentenceTransformer(self.model_name)
        embeddings = self.model.encode(input, batch_size=32, show_progress_bar=False)
        return embeddings.tolist()

_local_model = None

def get_embeddings_local(texts, model_name="BAAI/bge-m3", batch_size=16):
    global _local_model
    from sentence_transformers import SentenceTransformer
    
    if _local_model is None:
        print(f"\n正在加载本地 BGE-M3 向量模型 ({model_name})...")
        _local_model = SentenceTransformer(model_name)
    
    try:
        embeddings = _local_model.encode(texts, batch_size=batch_size, show_progress_bar=False)
        return embeddings.tolist()
    except Exception as e:
        # 如果默认的 MPS 设备报错（比如 Invalid buffer size 或 OOM），优雅降级到 CPU 计算
        print(f"\n[Warning] 硬件加速计算失败 ({str(e)})，正在为该文件优雅降级到 CPU 重新计算...")
        cpu_model = SentenceTransformer(model_name, device="cpu")
        embeddings = cpu_model.encode(texts, batch_size=batch_size, show_progress_bar=False)
        return embeddings.tolist()

def build_vector_db():
    parser = argparse.ArgumentParser(description="基于本地 BGE-M3 模型的《三国志》事件向量化与检索库构建工具")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--vectorize", action="store_true", help="第一步：将 raw 文件下的数据进行向量化，存到本地 cached 目录")
    group.add_argument("--save-chroma", action="store_true", help="第二步：将本地已向量化的文件读取并写入 ChromaDB")
    group.add_argument("--test", action="store_true", help="测试：从 ChromaDB 中进行语义检索测试")
    
    parser.add_argument("--force", action="store_true", help="如果已存在本地向量化文件，是否强制重新向量化 (默认跳过)")
    parser.add_argument("--collection-name", type=str, default="sanguozhi_events_bgem3", help="ChromaDB 中的 Collection 名称 (默认: sanguozhi_events_bgem3)")
    parser.add_argument("--model-name", type=str, default="BAAI/bge-m3", help="使用的 HuggingFace 本地模型名称 (默认: BAAI/bge-m3)")
    parser.add_argument("--batch-size", type=int, default=16, help="本地向量化时的批处理大小 (默认: 16)")
    
    args = parser.parse_args()

    if args.vectorize:
        raw_data_dir = os.path.join("data", "raw")
        vectors_dir = os.path.join("data", "vectors_bgem3")
        os.makedirs(vectors_dir, exist_ok=True)
        
        json_files = glob.glob(os.path.join(raw_data_dir, "*.json"))
        if not json_files:
            print(f"[Error] 未在 {raw_data_dir} 下找到任何 JSON 文件！")
            return
            
        print(f"开始本地 BGE-M3 向量化，共发现 {len(json_files)} 个 JSON 文件。目标目录: {vectors_dir}")
        
        for file_path in tqdm(json_files, desc="处理人物文件"):
            filename = os.path.basename(file_path)
            # 过滤不需要的文件或临时文件
            if filename.startswith(".") or not filename.endswith("_events.json"):
                continue
                
            person_name = filename.replace("_events.json", "")
            target_vector_path = os.path.join(vectors_dir, filename)
            
            # 如果已经向量化过了，除非指定了 --force，否则跳过
            if os.path.exists(target_vector_path) and not args.force:
                continue
                
            with open(file_path, "r", encoding="utf-8") as f:
                try:
                    events = json.load(f)
                except json.JSONDecodeError:
                    print(f"\n[Error] 无法解析 JSON 文件: {file_path}")
                    continue
            
            if not events:
                continue
                
            vectorized_events = []
            docs = []
            metadatas = []
            ids = []
            
            for idx, event in enumerate(events):
                title = event.get("事件标题", "")
                summary = event.get("事件简介", "")
                original_text = event.get("原文", "")
                
                document = f"标题：{title}\n简介：{summary}\n原文：{original_text}"
                
                metadata = {
                    "source_file": filename,
                    "person_name": person_name,
                    "title": title,
                    "type": event.get("事件类型", "不详"),
                    "location": event.get("地点", "不详"),
                    "start_year": event.get("std_start_year") if event.get("std_start_year") is not None else -1, 
                    "end_year": event.get("std_end_year") if event.get("std_end_year") is not None else -1
                }
                
                for k, v in metadata.items():
                    if not isinstance(v, (str, int, float, bool)):
                        metadata[k] = str(v)
                        
                doc_id = f"{person_name}_event_{idx}"
                
                docs.append(document)
                metadatas.append(metadata)
                ids.append(doc_id)
            
            # 批量获取本地 embeddings
            try:
                embeddings = get_embeddings_local(docs, model_name=args.model_name, batch_size=args.batch_size)
            except Exception as e:
                print(f"\n[Error] 向量化文件 {filename} 时发生错误: {str(e)}")
                continue
                
            for doc_id, doc, meta, emb in zip(ids, docs, metadatas, embeddings):
                vectorized_events.append({
                    "id": doc_id,
                    "document": doc,
                    "metadata": meta,
                    "embedding": emb
                })
                
            with open(target_vector_path, "w", encoding="utf-8") as f_out:
                json.dump(vectorized_events, f_out, ensure_ascii=False, indent=2)
                
        print("\n所有文件向量化完成！已保存在 data/vectors_bgem3 目录。")
        
    elif args.save_chroma:
        vectors_dir = os.path.join("data", "vectors_bgem3")
        chroma_db_dir = os.path.join("data", "chroma_db")
        os.makedirs(chroma_db_dir, exist_ok=True)
        
        vector_files = glob.glob(os.path.join(vectors_dir, "*.json"))
        if not vector_files:
            print(f"[Error] 未在 {vectors_dir} 下找到任何已向量化的 JSON 文件！请先运行 --vectorize 模式。")
            return
            
        print("正在初始化 ChromaDB 客户端...")
        client = chromadb.PersistentClient(path=chroma_db_dir)
        
        # 注册本地 BGE-M3 Embedding Function 以便后续查询时使用
        bgem3_ef = LocalBgem3EmbeddingFunction(model_name=args.model_name)
            
        collection = client.get_or_create_collection(
            name=args.collection_name,
            embedding_function=bgem3_ef,
            metadata={"hnsw:space": "cosine"}
        )
        
        docs = []
        embeddings = []
        metadatas = []
        ids = []
        
        print(f"读取已向量化文件，共 {len(vector_files)} 个...")
        for file_path in tqdm(vector_files, desc="读取本地向量"):
            filename = os.path.basename(file_path)
            if filename.startswith(".") or not filename.endswith("_events.json"):
                continue
                
            with open(file_path, "r", encoding="utf-8") as f:
                try:
                    items = json.load(f)
                except json.JSONDecodeError:
                    print(f"\n[Error] 无法解析向量文件: {file_path}")
                    continue
                    
            for item in items:
                ids.append(item["id"])
                docs.append(item["document"])
                metadatas.append(item["metadata"])
                embeddings.append(item["embedding"])
                
        batch_size = 2000
        print(f"\n开始写入 ChromaDB，共 {len(docs)} 条记录...")
        for i in tqdm(range(0, len(docs), batch_size), desc="写入 ChromaDB"):
            b_ids = ids[i:i + batch_size]
            b_docs = docs[i:i + batch_size]
            b_metas = metadatas[i:i + batch_size]
            b_embs = embeddings[i:i + batch_size]
            
            collection.upsert(
                ids=b_ids,
                documents=b_docs,
                metadatas=b_metas,
                embeddings=b_embs
            )
            
        print(f"\nChromaDB 写入完成！数据已持久化到 data/chroma_db，Collection 为 '{args.collection_name}'。")

    elif args.test:
        chroma_db_dir = os.path.join("data", "chroma_db")
        if not os.path.exists(chroma_db_dir):
            print(f"[Error] ChromaDB 目录 {chroma_db_dir} 不存在，请先使用 --save-chroma 导入数据！")
            return
            
        client = chromadb.PersistentClient(path=chroma_db_dir)
        bgem3_ef = LocalBgem3EmbeddingFunction(model_name=args.model_name)
        
        try:
            collection = client.get_collection(
                name=args.collection_name,
                embedding_function=bgem3_ef
            )
        except Exception as e:
            print(f"[Error] 找不到 Collection '{args.collection_name}': {str(e)}")
            return
            
        query = "关羽大意失荆州，败走麦城"
        print(f"\n正在对 '{query}' 进行语义检索...")
        results = collection.query(
            query_texts=[query],
            n_results=3
        )
        
        print("\n--- 检索结果 ---")
        for i, (doc, meta) in enumerate(zip(results['documents'][0], results['metadatas'][0])):
            print(f"\n[Result {i+1}] {meta.get('person_name', '未知')} - {meta.get('title', '无标题')}")
            print(f"内容: {doc[:150]}...")

if __name__ == "__main__":
    build_vector_db()
