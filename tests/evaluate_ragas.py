import os
import sys
import json
import time
import asyncio
from pathlib import Path
from dotenv import load_dotenv

# Ensure project root is in system path
_base_dir = os.path.dirname(os.path.abspath(__file__))
_root_dir = os.path.dirname(_base_dir)
if _root_dir not in sys.path:
    sys.path.append(_root_dir)

# Ensure backend/ is in sys.path for db/ and services/ resolution
_backend_dir = os.path.join(_root_dir, "backend")
if _backend_dir not in sys.path:
    sys.path.append(_backend_dir)

from agent.qa_agent import QAStreamPipeline, get_llm
from langchain_core.messages import SystemMessage, HumanMessage

load_dotenv()

JUDGE_SYSTEM_PROMPT = """
你是一位资深的三国正史学者与 AI 系统评测裁判。你专注于评估检索增强生成 (RAG) 管道的各项指标性能。
你必须以 JSON 格式输出你的评估打分，不要包含任何 markdown 代码块标记（如 ```json），以便程序能直接解析。
"""

JUDGE_PROMPT_TEMPLATE = """
请针对以下给出的“用户问题”、“系统生成的回答”、“参考历史概念”以及“检索到的工具上下文”，在以下四个 RAG 评估维度进行专业、客观的打分（0-10分），并给出具体的评价原因：

【评估维度与评分标准】：
1. 忠实度 (faithfulness_score)：
   - 评估系统生成的“回答”是否完全忠实于“检索到的工具上下文”。
   - 回答中所宣称的每一句史实（statements），是否都能在上下文数据中找到依据？
   - 若出现上下文依据之外的凭空捏造、幻觉、过度推论，需扣分。如果上下文为空且回答中包含大量事实阐述（全靠LLM预训练知识脑补），请评为 0 分（说明不忠实于检索到的零数据）。

2. 答案相关性 (answer_relevance_score)：
   - 评估生成的“回答”是否正面、切题、完整地回应了“用户问题”。
   - 回答是否啰嗦、答非所问，或者仅给出了错误/异常的拒绝回答？

3. 检索召回率 (context_recall_score)：
   - 评估“检索到的工具上下文”对“参考历史概念”的覆盖程度。
   - 检查参考概念列表中的每一个词。如果在检索到的工具数据中包含了有关该概念的事件/数据记录，视为已成功召回。
   - 计算召回概念占全部参考概念的比例（0-10分）。如果参考概念为空，本项请评分 10.0。

4. 检索精准度 (context_precision_score)：
   - 评估“检索到的工具上下文”中与“用户问题”相关的有用信息占比。
   - 检索出来的数据是不是大部分都有助于回答当前提问？是否拉取了大量无关的节点、地缘或噪音数据？

注意：如果检索上下文为空（说明是闲聊类型事件），请将 `faithfulness_score`、`context_recall_score` 和 `context_precision_score` 设为 -1，仅对 `answer_relevance_score` 进行评分。

【输入数据】：
用户问题：
{question}

系统生成的回答：
{answer}

参考历史概念/实体：
{reference}

检索到的工具上下文：
{context}

【输出格式】：
返回的 JSON 必须包含以下字段，并且可以直接被 json.loads 解析，请不要添加任何 markdown 代码包裹：
{{
  "faithfulness_score": 10.0,
  "faithfulness_reason": "评价原因...",
  "answer_relevance_score": 10.0,
  "answer_relevance_reason": "评价原因...",
  "context_recall_score": 10.0,
  "context_recall_reason": "评价原因...",
  "context_precision_score": 10.0,
  "context_precision_reason": "评价原因..."
}}
"""

async def evaluate_single_case(judge_llm, idx, item):
    question = item["question"]
    q_type = item["type"]
    reference = item.get("reference_concepts", [])
    
    print(f"\n─────────────────── [{idx+1}] [{q_type}] ───────────────────")
    print(f"提问: {question}")
    
    # 1. Execute RAG pipeline directly
    queue = asyncio.Queue()
    pipeline = QAStreamPipeline(question, history=[], queue=queue, handler=None)
    
    start_time = time.time()
    try:
        # Run pipeline task
        pipeline_task = asyncio.create_task(pipeline.execute_pipeline())
        
        # Consume the queue to let it run and log prints
        while not pipeline_task.done() or not queue.empty():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=0.05)
            except asyncio.TimeoutError:
                if pipeline_task.done() and queue.empty():
                    break
        
        await pipeline_task
        answer = "".join(pipeline.collected_text)
    except Exception as e:
        answer = f"Error generating answer: {e}"
        pipeline.all_observations = []
        
    duration = time.time() - start_time
    print(f"回答 ({duration:.2f}s):\n{answer}")
    
    # Format retrieved contexts
    context_str = ""
    if pipeline.all_observations:
        context_str = "\n\n".join([
            f"【工具: {obs['tool']} | 参数: {obs['query']}】\n数据: {obs['result']}"
            for obs in pipeline.all_observations
        ])
    else:
        context_str = "（未检索到任何工具数据 / 上下文为空）"
        
    # 2. Call LLM-as-a-Judge for all 4 metrics in one call
    judge_prompt = JUDGE_PROMPT_TEMPLATE.format(
        question=question,
        answer=answer,
        reference=", ".join(reference) if reference else "（无）",
        context=context_str
    )
    
    scores = {
        "faithfulness_score": -1.0,
        "faithfulness_reason": "Judge failed",
        "answer_relevance_score": -1.0,
        "answer_relevance_reason": "Judge failed",
        "context_recall_score": -1.0,
        "context_recall_reason": "Judge failed",
        "context_precision_score": -1.0,
        "context_precision_reason": "Judge failed"
    }
    
    print("🤔 Querying LLM-as-a-Judge for RAGAS metrics...")
    try:
        judge_res = (await asyncio.wait_for(
            judge_llm.ainvoke([
                SystemMessage(content=JUDGE_SYSTEM_PROMPT),
                HumanMessage(content=judge_prompt)
            ]),
            timeout=35.0
        )).content.strip()
        
        # Clean markdown codeblock wrap if any
        if judge_res.startswith("```json"):
            judge_res = judge_res[7:]
        elif judge_res.startswith("```"):
            judge_res = judge_res[3:]
        if judge_res.endswith("```"):
            judge_res = judge_res[:-3]
        judge_res = judge_res.strip()
        
        scores = json.loads(judge_res)
    except asyncio.TimeoutError:
        print("⚠️ Judge call timed out (exceeded 35s), applying fallback scores.")
    except Exception as err:
        print(f"⚠️ Judge call failed: {err}")
        
    print("⭐ RAGAS Scores:")
    print(f"  - 忠实度 (Faithfulness): {scores.get('faithfulness_score')}/10")
    print(f"  - 相关性 (Relevance):    {scores.get('answer_relevance_score')}/10")
    print(f"  - 召回率 (Recall):       {scores.get('context_recall_score')}/10")
    print(f"  - 精准度 (Precision):    {scores.get('context_precision_score')}/10")
    
    return {
        "question": question,
        "type": q_type,
        "reference": reference,
        "answer": answer,
        "latency": duration,
        "context": context_str,
        "scores": scores
    }

async def run_evaluation():
    eval_path = Path(_root_dir) / "tests" / "eval_dataset.json"
    if not eval_path.exists():
        print(f"❌ Evaluation dataset not found at {eval_path}")
        return
        
    with eval_path.open("r", encoding="utf-8") as f:
        dataset = json.load(f)
        
    print(f"📋 Loaded {len(dataset)} evaluation questions from dataset.")
    
    judge_llm = get_llm("complex")
    
    results = []
    print("\n🚀 Starting RAGAS Automated Evaluation Run...")
    
    for idx, item in enumerate(dataset):
        res = await evaluate_single_case(judge_llm, idx, item)
        results.append(res)
        
    # Calculate stats
    num_cases = len(dataset)
    
    def get_avg(metric_name):
        valid_vals = [
            float(r["scores"].get(metric_name, 0.0))
            for r in results
            if float(r["scores"].get(metric_name, -1.0)) >= 0
        ]
        return sum(valid_vals) / len(valid_vals) if valid_vals else 0.0

    avg_faith = get_avg("faithfulness_score")
    avg_relevance = get_avg("answer_relevance_score")
    avg_recall = get_avg("context_recall_score")
    avg_precision = get_avg("context_precision_score")
    avg_overall = (avg_faith + avg_relevance + avg_recall + avg_precision) / 4.0
    
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    report_dir = Path(_root_dir) / "logs" / "eval_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    
    md_content = f"""# 三国志 AI 幕僚系统 RAGAS 自动化评估报告

- **评估时间**: {time.strftime("%Y-%m-%d %H:%M:%S")}
- **样本数**: {num_cases} 个提问
- **评判大模型**: {judge_llm.model_name}

## 📊 RAG 核心指标评分

| 评估维度 | 平均得分 (0-10) | 指标阐释 |
| :--- | :---: | :--- |
| **忠实度 (Faithfulness)** | **{avg_faith:.2f}** | 回答是否有事实依据？是否存在脱离检索上下文的幻觉或编造 |
| **答案相关性 (Answer Relevance)** | **{avg_relevance:.2f}** | 回答是否正面、直接切题地响应了用户的提问，有无废话 |
| **检索召回率 (Context Recall)** | **{avg_recall:.2f}** | 检索到的工具上下文对参考历史实体/实体集（Reference Concepts）的覆盖程度 |
| **检索精准度 (Context Precision)** | **{avg_precision:.2f}** | 检索上下文的信息提炼密度，是否检索出了大量无关的冗余噪音数据 |
| **综合 RAG 得分 (Overall RAG)** | **{avg_overall:.2f}** | 四项核心维度的算术平均值 |

---

## 📝 详细评测记录

"""
    for idx, res in enumerate(results):
        scores = res["scores"]
        
        def show_score(val):
            return f"`{val}/10`" if float(val) >= 0 else "`不适用 (N/A)`"
            
        md_content += f"""### [{idx+1}] {res['question']}
- **任务类型**: `{res['type']}`
- **响应耗时**: `{res['latency']:.2f} 秒`
- **参考概念**: `{", ".join(res['reference']) if res['reference'] else "无"}`

#### 幕僚回答:
{res['answer']}

#### 检索到的上下文 (缩略):
```text
{res['context'][:800] + ('...' if len(res['context']) > 800 else '')}
```

#### RAGAS 评委细分项打分:
- **忠实度 (Faithfulness)**: {show_score(scores.get('faithfulness_score'))}
  > *评语*: {scores.get('faithfulness_reason')}
- **答案相关性 (Relevance)**: {show_score(scores.get('answer_relevance_score'))}
  > *评语*: {scores.get('answer_relevance_reason')}
- **检索召回率 (Recall)**: {show_score(scores.get('context_recall_score'))}
  > *评语*: {scores.get('context_recall_reason')}
- **检索精准度 (Precision)**: {show_score(scores.get('context_precision_score'))}
  > *评语*: {scores.get('context_precision_reason')}

---
"""

    # Write latest and timestamped report
    with (report_dir / "ragas_report_latest.md").open("w", encoding="utf-8") as f:
        f.write(md_content)
    with (report_dir / f"ragas_report_{timestamp}.md").open("w", encoding="utf-8") as f:
        f.write(md_content)
        
    print("\n" + "═" * 60)
    print(" 📊 三国志 AI 幕僚系统 RAGAS 评估报告汇总")
    print("═" * 60)
    print(f" 平均忠实度 (Faithfulness):   {avg_faith:.2f} / 10.0")
    print(f" 平均答案相关性 (Relevance):   {avg_relevance:.2f} / 10.0")
    print(f" 平均检索召回率 (Recall):      {avg_recall:.2f} / 10.0")
    print(f" 平均检索精准度 (Precision):   {avg_precision:.2f} / 10.0")
    print(f" 综合 RAG 得分 (Overall RAG): {avg_overall:.2f} / 10.0")
    print("═" * 60)
    print(f" 📄 评估报告已导出至: logs/eval_reports/ragas_report_latest.md")
    print("═" * 60 + "\n")

if __name__ == "__main__":
    asyncio.run(run_evaluation())
