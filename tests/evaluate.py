import os
import sys
import json
import time
from pathlib import Path
from dotenv import load_dotenv

# Ensure project root is in system path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.qa_agent import ask_question, get_llm
from langchain_core.messages import SystemMessage, HumanMessage

load_dotenv()

# Pricing maps for reporting
PRICING = {
    "deepseek-chat": {"input": 0.28, "output": 1.00},
    "qwen-plus": {"input": 0.50, "output": 1.50},
    "qwen-turbo": {"input": 0.30, "output": 0.60},
    "qwen-max": {"input": 2.00, "output": 6.00},
}

JUDGE_SYSTEM_PROMPT = """
你是一位资深的三国正史学者，担任本次三国志问答系统的裁判（LLM-as-a-Judge）。
你必须以JSON格式输出你的打分结果，不要有任何markdown代码块（如```json），以便程序能直接解析。
"""

JUDGE_PROMPT_TEMPLATE = """
请针对给出的“用户问题”、“系统生成的回答”以及“参考历史概念/实体”，在以下三个维度进行专业、客观的打分（0-10分），并给出具体的评价原因：

1. 史实准确度 (accuracy_score)：
   - 生成回答是否契合参考历史概念（reference_concepts）？
   - 是否存在明显的历史错误（如混淆演义与正史、时间错乱、人名张冠李戴）？
2. 引用合规性 (citation_compliance_score)：
   - 生成回答中是否泄露了任何技术词汇（如 Neo4j, Cypher, SQL, Database, LLM, prompt）？
   - 在数据库未检索到或出错时，回答是否能以学者风范进行自恰考证，并使用以古籍翻阅不便为由（如“简牍翻阅不便”）进行包装，严禁泄露技术细节？
3. 逻辑严密性 (logical_rigor_score)：
   - 答卷在行文、逻辑结构、条理性上是否优良？

请必须以 JSON 格式输出，确保没有 markdown 标记，可以直接被 json.loads 解析，包含以下 key:
{{
  "accuracy_score": 10,
  "accuracy_reason": "评价...",
  "citation_compliance_score": 10,
  "citation_compliance_reason": "评价...",
  "logical_rigor_score": 10,
  "logical_rigor_reason": "评价...",
  "overall_feedback": "评价..."
}}

用户问题：
{question}

参考历史概念/实体：
{reference}

系统生成的回答：
{answer}
"""

def run_evaluation():
    eval_path = Path(__file__).resolve().parent / "eval_dataset.json"
    if not eval_path.exists():
        print(f"❌ Evaluation dataset not found at {eval_path}")
        sys.exit(1)
        
    with eval_path.open("r", encoding="utf-8") as f:
        dataset = json.load(f)
        
    print(f"📋 Loaded {len(dataset)} evaluation questions from dataset.")
    
    # We will use qwen-plus or deepseek-chat for evaluation judge
    judge_llm = get_llm("complex")
    
    results = []
    
    total_acc = 0.0
    total_cit = 0.0
    total_rig = 0.0
    
    print("\n🚀 Starting Automated Evaluation Run...")
    
    for idx, item in enumerate(dataset):
        question = item["question"]
        q_type = item["type"]
        reference = item.get("reference_concepts", [])
        
        print(f"\n─────────────────── [{idx+1}/{len(dataset)}] [{q_type}] ───────────────────")
        print(f"提问: {question}")
        
        # 1. Get Agent Answer
        start_time = time.time()
        try:
            answer = ask_question(question, history=[])
        except Exception as e:
            answer = f"Error generating answer: {e}"
        duration = time.time() - start_time
        
        print(f"回答 ({duration:.2f}s):\n{answer}")
        
        # 2. Let the Judge evaluate
        judge_prompt = JUDGE_PROMPT_TEMPLATE.format(
            question=question,
            reference=", ".join(reference),
            answer=answer
        )
        
        scores = {
            "accuracy_score": 0.0,
            "accuracy_reason": "Judge query failed",
            "citation_compliance_score": 0.0,
            "citation_compliance_reason": "Judge query failed",
            "logical_rigor_score": 0.0,
            "logical_rigor_reason": "Judge query failed",
            "overall_feedback": "Judge query failed"
        }
        
        try:
            judge_res = judge_llm.invoke([
                SystemMessage(content=JUDGE_SYSTEM_PROMPT),
                HumanMessage(content=judge_prompt)
            ]).content.strip()
            
            # Clean markdown codeblock if returned
            if judge_res.startswith("```json"):
                judge_res = judge_res[7:]
            elif judge_res.startswith("```"):
                judge_res = judge_res[3:]
            if judge_res.endswith("```"):
                judge_res = judge_res[:-3]
            judge_res = judge_res.strip()
            
            scores = json.loads(judge_res)
        except Exception as err:
            print(f"⚠️ Judge call failed: {err}")
            
        print(f"⭐ Judge Scores -> 史实: {scores.get('accuracy_score')}/10 | 合规: {scores.get('citation_compliance_score')}/10 | 逻辑: {scores.get('logical_rigor_score')}/10")
        
        total_acc += float(scores.get("accuracy_score", 0.0))
        total_cit += float(scores.get("citation_compliance_score", 0.0))
        total_rig += float(scores.get("logical_rigor_score", 0.0))
        
        results.append({
            "question": question,
            "type": q_type,
            "reference": reference,
            "answer": answer,
            "latency": duration,
            "scores": scores
        })
        
    num_cases = len(dataset)
    avg_acc = total_acc / num_cases
    avg_cit = total_cit / num_cases
    avg_rig = total_rig / num_cases
    avg_score = (avg_acc + avg_cit + avg_rig) / 3.0
    
    # Format and save evaluation report
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    report_dir = Path("logs/eval_reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    
    md_content = f"""# 三国志 AI 幕僚系统自动化评估报告 (LLM-as-a-Judge)

- **评估时间**: {time.strftime("%Y-%m-%d %H:%M:%S")}
- **样本数**: {num_cases} 个提问
- **评判大模型**: {judge_llm.model_name}

## 📊 指标综合评分

| 评估维度 | 平均得分 (0-10) | 指标阐释 |
| :--- | :---: | :--- |
| **史实准确度 (Accuracy)** | **{avg_acc:.2f}** | 契合正史参考概念，不张冠李戴，不混淆演义 |
| **引用合规性 (Compliance)** | **{avg_cit:.2f}** | 无技术栈名词泄露，故障时保持学者风骨自恰包装 |
| **逻辑严密性 (Logical Rigor)** | **{avg_rig:.2f}** | 行文表达流畅，论证结构严密，有学者深度 |
| **综合总评分 (Overall)** | **{avg_score:.2f}** | 三项维度的算术平均分 |

---

## 📝 详细评测记录

"""
    for idx, res in enumerate(results):
        md_content += f"""### [{idx+1}] {res['question']}
- **任务类型**: `{res['type']}`
- **响应耗时**: `{res['latency']:.2f} 秒`
- **参考概念**: `{", ".join(res['reference'])}`

#### 幕僚回答:
{res['answer']}

#### 裁判评分:
- **史实准确度**: `{res['scores'].get('accuracy_score')}/10`
  > *评语*: {res['scores'].get('accuracy_reason')}
- **引用合规性**: `{res['scores'].get('citation_compliance_score')}/10`
  > *评语*: {res['scores'].get('citation_compliance_reason')}
- **逻辑严密性**: `{res['scores'].get('logical_rigor_score')}/10`
  > *评语*: {res['scores'].get('logical_rigor_reason')}
- **综合反馈**: {res['scores'].get('overall_feedback')}

---
"""
        
    # Write latest and timestamped report
    with (report_dir / "eval_report_latest.md").open("w", encoding="utf-8") as f:
        f.write(md_content)
    with (report_dir / f"eval_report_{timestamp}.md").open("w", encoding="utf-8") as f:
        f.write(md_content)
        
    # Terminal output Summary Dashboard
    print("\n" + "═" * 60)
    print(" 📊 三国志 AI 幕僚系统评估报告汇总")
    print("═" * 60)
    print(f" 平均史实准确度 (Accuracy):   {avg_acc:.2f} / 10.0")
    print(f" 平均引用合规性 (Compliance): {avg_cit:.2f} / 10.0")
    print(f" 平均逻辑严密性 (Rigor):      {avg_rig:.2f} / 10.0")
    print(f" 综合得分 (Overall Score):    {avg_score:.2f} / 10.0")
    print("═" * 60)
    print(f" 📄 评估报告已导出至: logs/eval_reports/eval_report_latest.md")
    print("═" * 60 + "\n")

if __name__ == "__main__":
    run_evaluation()
