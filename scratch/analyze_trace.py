import os
import sys
import json
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

load_dotenv()

# Official/SiliconFlow standard rates per 1,000,000 tokens
PRICING_REGISTRY = {
    "deepseek-v4-flash": {"input": 0.015, "output": 0.05},
    "deepseek-chat": {"input": 0.55, "output": 2.19},
    "deepseek-complex": {"input": 0.55, "output": 2.19},
    "gemini": {"input": 0.075, "output": 0.3},
    "gpt-4": {"input": 2.5, "output": 10.0},
    "gpt-3.5": {"input": 0.5, "output": 1.5},
    "default": {"input": 0.0, "output": 0.0}
}

def calculate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    matched = None
    model_lower = str(model_name).lower()
    for key in PRICING_REGISTRY:
        if key in model_lower:
            matched = PRICING_REGISTRY[key]
            break
    if not matched:
        matched = PRICING_REGISTRY["default"]
    
    in_cost = (input_tokens / 1_000_000) * matched["input"]
    out_cost = (output_tokens / 1_000_000) * matched["output"]
    return in_cost + out_cost

def format_msg(msg: dict) -> str:
    role = msg.get("role", "unknown").upper()
    name = msg.get("name")
    name_str = f" ({name})" if name else ""
    content = msg.get("content")
    
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
            if role == "TOOL":
                if isinstance(parsed, list):
                    summarized_list = []
                    for item in parsed:
                        if isinstance(item, dict):
                            summary_item = {k: item[k] for k in ["title", "year", "time", "id", "name", "score"] if k in item}
                            if "score" in summary_item and isinstance(summary_item["score"], (int, float)):
                                summary_item["score"] = round(summary_item["score"], 4)
                            summarized_list.append(summary_item)
                        else:
                            summarized_list.append(item)
                    content_str = (
                        f"// [Summarized Tool Output: {len(parsed)} items, Original raw size: {len(content)} chars]\n"
                        + json.dumps(summarized_list, ensure_ascii=False, indent=2)
                    )
                elif isinstance(parsed, dict) and "events" in parsed and isinstance(parsed["events"], list):
                    summarized_events = []
                    for item in parsed["events"]:
                        if isinstance(item, dict):
                            summary_item = {k: item[k] for k in ["title", "year", "time", "id", "name", "score"] if k in item}
                            if "score" in summary_item and isinstance(summary_item["score"], (int, float)):
                                summary_item["score"] = round(summary_item["score"], 4)
                            summarized_events.append(summary_item)
                        else:
                            summarized_events.append(item)
                    content_str = (
                        f"// [Summarized Tool Output: {len(parsed['events'])} events, Original raw size: {len(content)} chars]\n"
                        + json.dumps({"events": summarized_events}, ensure_ascii=False, indent=2)
                    )
                else:
                    content_str = json.dumps(parsed, ensure_ascii=False, indent=2)
            else:
                content_str = json.dumps(parsed, ensure_ascii=False, indent=2)
        except Exception:
            content_str = content
    else:
        content_str = str(content)
        
    return f"### 👤 {role}{name_str}\n```\n{content_str}\n```"

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scratch/analyze_trace.py <trace_id>")
        sys.exit(1)
        
    trace_id = sys.argv[1].strip()
    pub = os.environ.get("LANGFUSE_PUBLIC_KEY")
    sec = os.environ.get("LANGFUSE_SECRET_KEY")
    host = os.environ.get("LANGFUSE_HOST", "http://localhost:3001")
    
    if not pub or not sec:
        print("Error: LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY not set in .env file.")
        sys.exit(1)
        
    url = f"{host}/api/public/traces/{trace_id}"
    print(f"📡 Fetching trace data from {url}...")
    
    res = requests.get(url, auth=HTTPBasicAuth(pub, sec))
    if res.status_code != 200:
        print(f"❌ Failed to fetch trace: {res.status_code} - {res.text}")
        sys.exit(1)
        
    data = res.json()
    print("✅ Trace data retrieved successfully.")
    
    observations = data.get("observations", [])
    observations.sort(key=lambda x: x.get("startTime", ""))
    
    # Filter generations and spans
    generations = [obs for obs in observations if obs.get("type") == "GENERATION"]
    spans = [obs for obs in observations if obs.get("type") == "SPAN"]
    
    # ------------------ Compile Aggregated Execution Summary ------------------
    pipeline_total_tokens = 0
    pipeline_total_in = 0
    pipeline_total_out = 0
    pipeline_total_cost = 0.0
    pipeline_total_latency = 0.0
    
    step_summaries = []
    for idx, gen in enumerate(generations):
        name = gen.get("name", "Generation")
        model = gen.get("model", "unknown")
        latency = gen.get("latency", 0.0)
        in_t = gen.get("promptTokens", 0) or 0
        out_t = gen.get("completionTokens", 0) or 0
        tot_t = gen.get("totalTokens", 0) or 0
        cost = calculate_cost(model, in_t, out_t)
        
        pipeline_total_in += in_t
        pipeline_total_out += out_t
        pipeline_total_tokens += tot_t
        pipeline_total_cost += cost
        pipeline_total_latency += latency
        
        step_summaries.append(f"| G{idx+1} | {name} | `{model}` | {latency:.2f}s | {in_t:,} | {out_t:,} | ${cost:.6f} |")

    # ------------------ Extract Specific Agent Steps ------------------
    intent_gen = None
    planning_gen = None
    synthesis_gen = None
    
    for gen in generations:
        prompt_str = str(gen.get("input", ""))
        output_str = str(gen.get("output", ""))
        gen_name = str(gen.get("name", ""))
        
        if "INTENT_ANALYSIS_PROMPT" in prompt_str or "意图拆解与问题重写" in prompt_str or gen_name == "IntentAgent":
            intent_gen = gen
        elif "PLANNING_PROMPT" in prompt_str or "任务步骤（DAG）" in prompt_str or "DAGPlan" in output_str or gen_name == "PlannerAgent":
            planning_gen = gen
        elif "ANSWER_TEMPLATE" in prompt_str or "请以一名优秀的《三国志》历史学大家口吻回答" in prompt_str or gen_name == "SynthesisAgent":
            synthesis_gen = gen

    # Find tool spans
    tool_spans = []
    allowed_tools = ["query_neo4j_async", "get_person_timeline_async", "search_vector_graph_async", "search_historical_text_async"]
    for s in spans:
        if s.get("name") in allowed_tools:
            tool_spans.append(s)

    # ------------------ Write Report Markdown ------------------
    md = []
    md.append(f"# 📊 Langfuse Agent Trace Analysis: `{trace_id}`")
    md.append(f"- **Trace Name**: `{data.get('name')}`")
    md.append(f"- **User Top Question**: `{data.get('input')}`")
    md.append(f"- **Total Spans**: `{len(spans)}` | **Total LLM Generations**: `{len(generations)}` steps")
    md.append(f"- **Status Message**: `{data.get('statusMessage')}`")
    md.append("\n---\n")
    
    md.append("## 📈 Execution Summary (Aggregated)")
    md.append("| Step | Step Name | Model | Latency | Input Tokens | Output Tokens | Est. Cost (USD) |")
    md.append("| :--- | :--- | :--- | :---: | :---: | :---: | :---: |")
    md.extend(step_summaries)
    md.append(f"| **Total** | - | - | **{pipeline_total_latency:.2f}s** | **{pipeline_total_in:,}** | **{pipeline_total_out:,}** | **${pipeline_total_cost:.6f}** |")
    md.append("\n---\n")
    
    md.append("## 🧩 Agent 核心步骤与数据流分析")
    
    # 1. Intent Analysis
    md.append("### 1. 对话意图分析与问题重写 (Intent & Rewrite)")
    if intent_gen:
        inp_val = intent_gen.get("input")
        outp_val = intent_gen.get("output")
        model = intent_gen.get("model", "unknown")
        latency = intent_gen.get("latency", 0.0)
        in_t = intent_gen.get("promptTokens", 0) or 0
        out_t = intent_gen.get("completionTokens", 0) or 0
        cost = calculate_cost(model, in_t, out_t)
        
        md.append(f"- **耗时与模型**: `{latency:.2f}s` | Model: `{model}`")
        md.append(f"- **Token用量**: Input `{in_t:,}` -> Output `{out_t:,}` (成本: `${cost:.6f}`)")
        
        rewritten_q = "N/A"
        entities = []
        historical_chars = []
        q_type = "N/A"
        
        if isinstance(outp_val, dict):
            tcs = outp_val.get("additional_kwargs", {}).get("tool_calls", [])
            for tc in tcs:
                args_str = tc.get("function", {}).get("arguments", "{}")
                try:
                    args = json.loads(args_str)
                    rewritten_q = args.get("rewritten_question", rewritten_q)
                    entities = args.get("entities", [])
                    historical_chars = args.get("historical_characters", [])
                    q_type = args.get("type", q_type)
                except Exception:
                    pass
        elif isinstance(outp_val, str):
            try:
                parsed = json.loads(outp_val)
                rewritten_q = parsed.get("rewritten_question", rewritten_q)
                entities = parsed.get("entities", [])
                historical_chars = parsed.get("historical_characters", [])
                q_type = parsed.get("type", q_type)
            except Exception:
                rewritten_q = outp_val
                
        md.append(f"- **判定分类 (Type)**: `{q_type}`")
        md.append(f"- **重写后问题 (Rewritten Question)**: `\"{rewritten_q}\"`")
        md.append(f"- **提取的实体 (Entities)**: `{entities}`")
        md.append(f"- **提及的历史人物 (Characters)**: `{historical_chars}`")
    else:
        md.append("*(未在此 trace 中发现独立的意图判定步骤)*")
    md.append("\n" + "-"*40 + "\n")
    
    # 2. Planning / Deconstruction
    md.append("### 2. 问题拆解与规划 (Deconstruction & Planning)")
    if planning_gen:
        outp_val = planning_gen.get("output")
        model = planning_gen.get("model", "unknown")
        latency = planning_gen.get("latency", 0.0)
        in_t = planning_gen.get("promptTokens", 0) or 0
        out_t = planning_gen.get("completionTokens", 0) or 0
        cost = calculate_cost(model, in_t, out_t)
        
        thought = "N/A"
        tasks = []
        
        if isinstance(outp_val, dict):
            tcs = outp_val.get("additional_kwargs", {}).get("tool_calls", [])
            for tc in tcs:
                args_str = tc.get("function", {}).get("arguments", "{}")
                try:
                    args = json.loads(args_str)
                    thought = args.get("thought", thought)
                    tasks = args.get("tasks", [])
                except Exception:
                    pass
        elif isinstance(outp_val, str):
            try:
                parsed = json.loads(outp_val)
                thought = parsed.get("thought", thought)
                tasks = parsed.get("tasks", [])
            except Exception:
                thought = outp_val
                
        md.append(f"- **耗时与模型**: `{latency:.2f}s` | Model: `{model}`")
        md.append(f"- **Token用量**: Input `{in_t:,}` -> Output `{out_t:,}` (成本: `${cost:.6f}`)")
        md.append(f"- **规划思考过程 (Thinking)**:\n  > {thought}")
        md.append("- **拆解的有向无环任务步骤 (Tasks)**:")
        if tasks:
            for t in tasks:
                deps = t.get("dependencies", [])
                deps_str = f" (依赖: {deps})" if deps else ""
                md.append(f"  * **`[{t.get('id')}]`** 调用 `{t.get('tool')}`{deps_str}")
                md.append(f"    - 参数 (Args): `{t.get('args')}`")
        else:
            md.append("  *(无任务步骤)*")
    else:
        md.append("*(未在此 trace 中发现独立的复杂规划步骤)*")
    md.append("\n" + "-"*40 + "\n")
    
    # 3. Sub-queries Execution & Text-to-Cypher
    md.append("### 3. 子问题执行与 Cypher 转化 (Execution & Text-to-Cypher)")
    if tool_spans:
        for idx, span in enumerate(tool_spans):
            span_id = span.get("id")
            name = span.get("name")
            latency = span.get("latency", 0.0)
            inp_args = span.get("input")
            outp_res = span.get("output")
            
            # Find any generations under this span (Cypher Translation / Corrector calls)
            child_gens = [g for g in generations if g.get("parentObservationId") == span_id]
            
            md.append(f"#### ➡️ 子任务 T{idx+1}: `{name}`")
            md.append(f"- **执行总耗时**: `{latency:.2f}s`")
            md.append(f"- **传入参数 (Input Args)**: `{inp_args}`")
            
            if child_gens:
                md.append("- **LLM 辅助转换/纠错过程 (Text-to-Cypher)**:")
                for c_idx, cg in enumerate(child_gens):
                    cg_model = cg.get("model", "unknown")
                    cg_lat = cg.get("latency", 0.0)
                    cg_in_t = cg.get("promptTokens", 0) or 0
                    cg_out_t = cg.get("completionTokens", 0) or 0
                    cg_cost = calculate_cost(cg_model, cg_in_t, cg_out_t)
                    
                    cg_prompt = str(cg.get("input", ""))
                    cg_out = str(cg.get("output", ""))
                    if isinstance(cg.get("output"), dict):
                        cg_out = cg.get("output", {}).get("content") or str(cg.get("output"))
                        
                    is_correction = "自修正" in cg_prompt or "修正语法" in cg_prompt or "修正后" in cg_prompt or cg_prompt.count("human") > 1
                    phase_str = f"自修正第 {c_idx} 次" if is_correction else "首次翻译"
                    
                    md.append(f"  * **[{phase_str}]** `{cg_model}` | 耗时 `{cg_lat:.2f}s` | Token In/Out: `{cg_in_t}/{cg_out_t}` (成本: `${cg_cost:.6f}`)")
                    md.append(f"    - **生成的 Cypher**: \n```cypher\n{cg_out.strip()}\n```")
            
            # Tool result
            res_str = ""
            if isinstance(outp_res, str):
                res_str = outp_res
            else:
                res_str = json.dumps(outp_res, ensure_ascii=False, indent=2)
            
            # Limit the output snippet size
            if len(res_str) > 1000:
                res_str = res_str[:1000] + "\n\n... (为了可读性，过长检索结果已被截断) ..."
                
            md.append(f"- **检索返回结果 (Output)**: \n```json\n{res_str}\n```")
            md.append("\n")
    else:
        md.append("*(没有执行任何图谱/向量原子检索工具)*")
    md.append("\n" + "-"*40 + "\n")
    
    # 4. Synthesis
    md.append("### 4. 最终答案组装与生成 (Final Synthesis)")
    if synthesis_gen:
        model = synthesis_gen.get("model", "unknown")
        latency = synthesis_gen.get("latency", 0.0)
        in_t = synthesis_gen.get("promptTokens", 0) or 0
        out_t = synthesis_gen.get("completionTokens", 0) or 0
        cost = calculate_cost(model, in_t, out_t)
        
        outp_val = synthesis_gen.get("output", {})
        final_answer = outp_val.get("content") if isinstance(outp_val, dict) else str(outp_val)
        
        md.append(f"- **耗时与模型**: `{latency:.2f}s` | Model: `{model}`")
        md.append(f"- **Token用量**: Input `{in_t:,}` -> Output `{out_t:,}` (成本: `${cost:.6f}`)")
        md.append(f"- **最终组装答案 (Final Answer Preview)**:\n\n{final_answer.strip()}")
    else:
        md.append("*(未在此 trace 中发现独立的最终合成步骤)*")
    md.append("\n---\n")
    
    # Add raw detailed breakdown at the bottom as reference
    md.append("## 🔍 Detailed Raw Trace Steps (Reference)")
    for idx, gen in enumerate(generations):
        name = gen.get("name", "Generation")
        model = gen.get("model", "unknown")
        latency = gen.get("latency", 0.0)
        in_t = gen.get("promptTokens", 0) or 0
        out_t = gen.get("completionTokens", 0) or 0
        tot_t = gen.get("totalTokens", 0) or 0
        cost = calculate_cost(model, in_t, out_t)
        
        md.append(f"### ➡️ G{idx+1}: {name} ({model})")
        md.append(f"- **Duration**: `{latency:.2f}s` | **Cost**: `${cost:.6f}`")
        md.append(f"- **Tokens**: Input `{in_t:,}` -> Output `{out_t:,}` (Total: `{tot_t:,}`)")
        md.append("\n#### 📥 Prompt Context (Input Messages)")
        
        inp = gen.get("input")
        if isinstance(inp, list):
            for msg in inp:
                md.append(format_msg(msg))
        else:
            md.append(f"```\n{inp}\n```")
            
        md.append("\n#### 📤 Model Response (Output)")
        outp = gen.get("output", {})
        out_content = ""
        if isinstance(outp, dict):
            out_content = outp.get("content") or ""
            tcs = outp.get("additional_kwargs", {}).get("tool_calls", [])
            if tcs:
                md.append("🔧 **Tool Calls Triggered**:")
                for tc in tcs:
                    func = tc.get("function", {})
                    md.append(f"- Tool: `{func.get('name')}` | Args: `{func.get('arguments')}`")
        elif isinstance(outp, str):
            try:
                parsed = json.loads(outp)
                out_content = parsed.get("content") or outp
            except Exception:
                out_content = outp
                
        md.append(f"```\n{out_content.strip()}\n```")
        md.append("\n" + "="*80 + "\n")
        
    report_content = "\n".join(md)
    
    # Save to file
    report_file = f"scratch/trace_{trace_id}_report.md"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report_content)
        
    # Also print summary to terminal
    print("\n" + "="*50)
    print(f"📊 SUMMARY REPORT FOR TRACE {trace_id}")
    print(f"Total Steps: {len(generations)}")
    print(f"Total Latency: {pipeline_total_latency:.2f}s")
    print(f"Total Tokens: In={pipeline_total_in:,} | Out={pipeline_total_out:,} | Total={pipeline_total_tokens:,}")
    print(f"Total Estimated Cost: ${pipeline_total_cost:.6f} USD")
    print(f"💾 Full detailed breakdown written to: {report_file}")
    print("="*50 + "\n")

if __name__ == "__main__":
    main()
