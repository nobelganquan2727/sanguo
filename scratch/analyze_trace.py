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
    "default": {"input": 0.0, "output": 0.0}
}

def calculate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    # Match model name
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
    
    # Try formatting JSON content for tools or system messages
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
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
    
    # Sort generations
    generations = [obs for obs in data.get("observations", []) if obs.get("type") == "GENERATION"]
    generations.sort(key=lambda x: x.get("startTime", ""))
    
    # Start compiling report
    md = []
    md.append(f"# 📊 Langfuse Trace Analysis: `{trace_id}`")
    md.append(f"- **Trace Name**: `{data.get('name')}`")
    md.append(f"- **User Top Question**: `{data.get('input')}`")
    md.append(f"- **Total Generations**: `{len(generations)}` steps")
    md.append(f"- **Status Message**: `{data.get('statusMessage')}`")
    md.append("\n---\n")
    
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
        in_t = gen.get("promptTokens", 0)
        out_t = gen.get("completionTokens", 0)
        tot_t = gen.get("totalTokens", 0)
        cost = calculate_cost(model, in_t, out_t)
        
        pipeline_total_in += in_t
        pipeline_total_out += out_t
        pipeline_total_tokens += tot_t
        pipeline_total_cost += cost
        pipeline_total_latency += latency
        
        step_summaries.append(f"| G{idx+1} | {name} | `{model}` | {latency:.2f}s | {in_t:,} | {out_t:,} | ${cost:.6f} |")
        
    md.append("## 📈 Execution Summary (Aggregated)")
    md.append("| Step | Step Name | Model | Latency | Input Tokens | Output Tokens | Est. Cost (USD) |")
    md.append("| :--- | :--- | :--- | :---: | :---: | :---: | :---: |")
    md.extend(step_summaries)
    md.append(f"| **Total** | - | - | **{pipeline_total_latency:.2f}s** | **{pipeline_total_in:,}** | **{pipeline_total_out:,}** | **${pipeline_total_cost:.6f}** |")
    md.append("\n---\n")
    
    md.append("## 🔍 Detailed Step-by-Step Breakdown")
    
    for idx, gen in enumerate(generations):
        name = gen.get("name", "Generation")
        model = gen.get("model", "unknown")
        latency = gen.get("latency", 0.0)
        in_t = gen.get("promptTokens", 0)
        out_t = gen.get("completionTokens", 0)
        tot_t = gen.get("totalTokens", 0)
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
            # Display tool calls if any
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
