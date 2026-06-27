#!/usr/bin/env python3
"""
Sanguozhi Agent - Automated Evaluation & Regression Testing Runner
Based on LangChain + Langfuse (LLM-as-Judge)

Usage:
  # Run evaluation
  python scripts/run_evaluation.py --run-name "baseline-v1"

  # Seed dataset only without running evaluation
  python scripts/run_evaluation.py --seed-only
"""

import os
import sys
import json
import argparse
import datetime
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Ensure the root directory is in python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

from langfuse import Langfuse
from langchain_core.messages import SystemMessage, HumanMessage
from agent.qa_agent import ask_question
from agent.tools import get_llm

# --- Configuration & Pydantic Models for Judge ---

class DimensionScore(BaseModel):
    score: int = Field(description="打分分值，范围 1 到 5。1表示极差/完全不符合，5表示完美符合。")
    reason: str = Field(description="打分的具体理由和诊断分析，指出亮点或不足。")

class EvaluationResult(BaseModel):
    historical_accuracy: DimensionScore = Field(description="史实准确度评估。检查是否符合常理或符合给定的参考/标准答案，是否存在史实捏造。")
    persona_consistency: DimensionScore = Field(description="人设拟真度评估。评估是否符合学者/古代幕僚（自称老夫、儒雅、文风古风）的语气，是否夹杂了现代AI感。")
    defensiveness: DimensionScore = Field(description="严谨性与防御力评估。评估面对越界提问（如哈利波特）或数据库查无此信息时，是否坚守原则拒绝胡编，或者在无记录时优雅退水。")

# --- Prompts ---

JUDGE_SYSTEM_PROMPT = """你是一位极其严苛的三国正史学家与大语言模型评估专家。
你的任务是评估一个“三国正史考证学者/幕僚人设智能体”的回答质量。

请根据用户输入（提问）、期望的参考回答（期望行为）、智能体实际回答，客观且严苛地对智能体的回答进行三个维度的评估：

1. 史实准确度 (historical_accuracy)
   - 满分 5 分。评估智能体的回答在历史事实上是否准确。
   - 如果智能体犯了明显的史实错误、生卒年错乱、战役参与者颠倒，或者和公认的《三国志》正史严重冲突，扣分（1-3分）。
   - 如果回答完全符合正史且逻辑通顺，给 5 分。

2. 人设拟真度 (persona_consistency)
   - 满分 5 分。评估智能体是否维持了“三国考证幕僚/老学究”的语气（自称“老夫”、“阁下”，用词文雅古朴，具有书卷气，绝不带有现代AI腔调）。
   - 如果智能体的回答里夹杂了现代 AI 的口吻（如“作为一个人工智能模型...”、“为您服务...”、“当然可以，以下是...”、“总的来说，...”），或者语气干瘪机械，扣分（1-3分）。
   - 如果始终维持极高水准的幕僚古风语气，给 5 分。

3. 严谨性与防御力 (defensiveness)
   - 满分 5 分。评估智能体在面对“数据库无记录”、“超出三国正史范畴”或者“虚构人物/穿越提问”时的防御能力。
   - 如果用户问了虚构/越界人物（如哈利波特），智能体必须坚决拒绝并指出正史无载；如果数据库查无此项，智能体必须诚实说明藏书阁无相关记载，基于自身知识谨慎作答，绝对不能为了迎合用户而胡编乱造。
   - 如果用户问了虚构无理问题，智能体迎合胡编（例如编造哈利波特在赤壁之战放魔法），或者系统报错泄露了技术底层词汇（如 Neo4j, Cypher, Python 等），扣至 1-2 分。
   - 如果防御完美，表现极其严谨，给 5 分。

你必须提供极其详细、事实求是的评估理由，解释为什么给出该分数，并指出具体的改进建议。
"""

JUDGE_USER_PROMPT = """【用户提问】: {question}
【期望参考/目标行为】: {expected_output}
【智能体实际回答】: {actual_output}

请进行客观评估并输出结构化 JSON 结果。
"""

# --- Seed Test Cases ---

_eval_dir = os.path.dirname(os.path.abspath(__file__))
_json_path = os.path.join(_eval_dir, "seed_test_cases.json")
try:
    with open(_json_path, "r", encoding="utf-8") as _f:
        SEED_TEST_CASES = json.load(_f)
except Exception as _e:
    print(f"❌ [初始化] 无法读取种子用例文件 {_json_path}: {_e}")
    SEED_TEST_CASES = []

DATASET_NAME = "sanguo_qa_dataset_v2"

# --- Functions ---

def seed_dataset(langfuse_client: Langfuse):
    """Seeds the test dataset in Langfuse if it doesn't exist."""
    print(f"📦 [数据集] 正在检查 Langfuse 数据集 '{DATASET_NAME}'...")
    try:
        # Check if dataset exists
        dataset = langfuse_client.get_dataset(DATASET_NAME)
        print(f"✅ [数据集] 数据集已存在，包含 {len(dataset.items)} 个测试用例。")
    except Exception:
        print(f"🆕 [数据集] 数据集不存在，正在创建并导入 {len(SEED_TEST_CASES)} 个核心测试用例...")
        dataset = langfuse_client.create_dataset(name=DATASET_NAME, description="三国正史智能体问答评估回归测试集")
        
        for item in SEED_TEST_CASES:
            langfuse_client.create_dataset_item(
                dataset_name=DATASET_NAME,
                input=item["input"],
                expected_output=item["expected_output"]
            )
        print(f"🎉 [数据集] 成功导入 {len(SEED_TEST_CASES)} 个测试用例！")
        # Re-fetch to confirm
        dataset = langfuse_client.get_dataset(DATASET_NAME)
    return dataset


def run_judge(question: str, expected_output: str, actual_output: str) -> EvaluationResult:
    """Invokes the LLM-as-Judge to score the agent's response."""
    llm = get_llm("complex")
    
    system_msg = SystemMessage(content=JUDGE_SYSTEM_PROMPT)
    user_msg = HumanMessage(content=JUDGE_USER_PROMPT.format(
        question=question,
        expected_output=expected_output,
        actual_output=actual_output
    ))
    
    # Try structured output first
    try:
        structured_llm = llm.with_structured_output(EvaluationResult, method="function_calling")
        result = structured_llm.invoke([system_msg, user_msg])
        return result
    except Exception as e:
        print(f"⚠️ [裁判] 结构化输出失败 ({e})，正在尝试 JSON 兜底解析...")
        # Fallback to raw JSON generation and parsing
        try:
            json_llm = get_llm("complex")
            fallback_prompt = JUDGE_USER_PROMPT.format(
                question=question,
                expected_output=expected_output,
                actual_output=actual_output
            ) + "\n请严格返回一个符合 schema 的 JSON 对象，不要包含 markdown 代码块。JSON 格式如下:\n" + json.dumps({
                "historical_accuracy": {"score": 5, "reason": "理由"},
                "persona_consistency": {"score": 5, "reason": "理由"},
                "defensiveness": {"score": 5, "reason": "理由"}
            }, ensure_ascii=False)
            
            res_msg = json_llm.invoke([
                SystemMessage(content=JUDGE_SYSTEM_PROMPT + " You must output raw JSON only."),
                HumanMessage(content=fallback_prompt)
            ])
            
            content = res_msg.content.strip()
            if content.startswith("```json"):
                content = content[7:]
            elif content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            data = json.loads(content)
            return EvaluationResult(
                historical_accuracy=DimensionScore(**data["historical_accuracy"]),
                persona_consistency=DimensionScore(**data["persona_consistency"]),
                defensiveness=DimensionScore(**data["defensiveness"])
            )
        except Exception as e2:
            print(f"❌ [裁判] 兜底解析也失败了: {e2}。将使用默认 1 分垫底。")
            return EvaluationResult(
                historical_accuracy=DimensionScore(score=1, reason=f"评估程序异常: {e2}"),
                persona_consistency=DimensionScore(score=1, reason=f"评估程序异常: {e2}"),
                defensiveness=DimensionScore(score=1, reason=f"评估程序异常: {e2}")
            )


def main():
    parser = argparse.ArgumentParser(description="Sanguozhi Agent Evaluation & Regression Testing Runner")
    parser.add_argument("--run-name", type=str, default="", help="评估运行的名称 (如 'v1-baseline'，默认以时间戳命名)")
    parser.add_argument("--seed-only", action="store_true", help="仅初始化/注入测试数据集，不跑评估")
    parser.add_argument("--max-cases", type=int, default=10, help="最大评估用例数")
    args = parser.parse_args()
    
    langfuse_client = Langfuse()
    
    # 1. Ensure dataset exists
    dataset = seed_dataset(langfuse_client)
    
    if args.seed_only:
        print("💡 --seed-only 参数已指定，已退出。")
        sys.exit(0)
        
    # 2. Determine Run Name
    run_name = args.run_name
    if not run_name:
        run_name = f"run_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
    print(f"\n🚀 [评估启动] 开始运行评估集测试。运行名称: \033[1;36m{run_name}\033[0m")
    print("=" * 80)
    
    results = []
    total_items = min(len(dataset.items), args.max_cases)
    
    # 3. Iterate over dataset items
    for idx, item in enumerate(dataset.items[:total_items]):
        question = item.input
        expected = item.expected_output
        print(f"\n📝 [\033[1;33m{idx+1}/{total_items}\033[0m] 提问: \"{question}\"")
        print("-" * 50)
        
        # We pass a dict to capture the trace ID asynchronously
        trace_meta = {}
        
        # Execute the agent
        print("🤖 [Agent] 思考中并翻检书箧...")
        try:
            actual_answer = ask_question(question, history=[], dataset_item_id=item.id, trace_metadata=trace_meta)
        except Exception as e:
            print(f"❌ [Agent] 执行失败: {e}")
            actual_answer = f"⚠️ [系统错误]: {e}"
            
        trace_id = trace_meta.get("trace_id")
        print(f"📥 [Agent] 回答完成 (Trace ID: {trace_id or '未知'})")
        print(f"💬 [回答内容]: \033[0;32m{actual_answer[:120]}...\033[0m")
        
        # 4. LLM-as-Judge Grading
        if trace_id:
            # Link trace to the named dataset run in Langfuse
            try:
                item.link(None, run_name=run_name, trace_id=trace_id)
                print(f"🔗 [Langfuse] 成功关联 Trace 到运行 '{run_name}'")
            except Exception as e:
                print(f"⚠️ [Langfuse] 关联运行失败: {e}")

            print("⚖️ [裁判] 正在根据史料和期望行为客观打分...")
            eval_res = run_judge(question, expected, actual_answer)
            
            # Log scores back to Langfuse
            try:
                langfuse_client.score(
                    trace_id=trace_id,
                    name="historical_accuracy",
                    value=eval_res.historical_accuracy.score,
                    comment=eval_res.historical_accuracy.reason
                )
                langfuse_client.score(
                    trace_id=trace_id,
                    name="persona_consistency",
                    value=eval_res.persona_consistency.score,
                    comment=eval_res.persona_consistency.reason
                )
                langfuse_client.score(
                    trace_id=trace_id,
                    name="defensiveness",
                    value=eval_res.defensiveness.score,
                    comment=eval_res.defensiveness.reason
                )
                print("✅ [Langfuse] 评分成功上传！")
            except Exception as e:
                print(f"⚠️ [Langfuse] 评分上传失败: {e}")
                
            results.append({
                "question": question,
                "answer": actual_answer,
                "scores": eval_res,
                "trace_id": trace_id
            })
            
            # Print intermediate grades
            print(f"📊 [打分结果] "
                  f"史实准确度: \033[1;32m{eval_res.historical_accuracy.score}/5\033[0m | "
                  f"人设拟真度: \033[1;32m{eval_res.persona_consistency.score}/5\033[0m | "
                  f"严谨防御力: \033[1;32m{eval_res.defensiveness.score}/5\033[0m")
        else:
            print("⚠️ [裁判] 未获取到 Trace ID，跳过打分。")
            
    # 5. Output Gorgeous Console Summary
    print("\n" + "=" * 80)
    print("🏁 \033[1;35m评估测试完成！以下为量化诊断报告\033[0m")
    print("=" * 80)
    
    if not results:
        print("❌ 没有成功评估的测试数据。")
        return
        
    avg_accuracy = sum(r["scores"].historical_accuracy.score for r in results) / len(results)
    avg_persona = sum(r["scores"].persona_consistency.score for r in results) / len(results)
    avg_defense = sum(r["scores"].defensiveness.score for r in results) / len(results)
    avg_total = (avg_accuracy + avg_persona + avg_defense) / 3
    
    print(f"📊 **平均表现汇总 (Run Name: {run_name})**")
    print(f"  - 史实准确度 (Accuracy):      \033[1;36m{avg_accuracy:.2f} / 5.0\033[0m")
    print(f"  - 人设拟真度 (Persona):       \033[1;36m{avg_persona:.2f} / 5.0\033[0m")
    print(f"  - 严谨与防御力 (Defense):     \033[1;36m{avg_defense:.2f} / 5.0\033[0m")
    print(f"  - \033[1;33m综合平均得分 (Overall):       {avg_total:.2f} / 5.0\033[0m")
    print("-" * 80)
    
    print("🔍 **测试用例详细明细：**")
    for idx, r in enumerate(results):
        scores = r["scores"]
        print(f"[{idx+1}] \033[1m{r['question']}\033[0m")
        print(f"    - Accuracy: {scores.historical_accuracy.score}/5  (理由: {scores.historical_accuracy.reason[:60]}...)")
        print(f"    - Persona:  {scores.persona_consistency.score}/5  (理由: {scores.persona_consistency.reason[:60]}...)")
        print(f"    - Defense:  {scores.defensiveness.score}/5  (理由: {scores.defensiveness.reason[:60]}...)")
        print(f"    - Trace URL: {os.environ.get('LANGFUSE_HOST', 'http://localhost:3000')}/trace/{r['trace_id']}")
        print()
        
    print("=" * 80)
    print("💡 **建议闭环操作 (Measurement -> Diagnosis -> Improvement -> Re-measurement):**")
    print("  1. 打开 Langfuse 平台: \033[4;34mhttp://localhost:3001/datasets/sanguo_qa_dataset\033[0m")
    print("  2. 查看本次 Run \033[1;36m" + run_name + "\033[0m 的表现，诊断分数偏低的项目。")
    print("  3. 修改 `agent/prompts.py` 中的人设词或 `agent/tools.py` 中的检索逻辑。")
    print("  4. 重新运行本脚本并指定新 --run-name，在 UI 中对比两次运行的得分，直到平均分持续上升！")
    print("=" * 80)
    
    # Flush Langfuse client to ensure everything is sent
    langfuse_client.flush()

if __name__ == "__main__":
    main()
