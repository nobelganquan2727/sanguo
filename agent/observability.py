import os
import time
import json
import uuid
from typing import Dict, Any, List, Optional
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from contextvars import ContextVar

active_callback_var: ContextVar[Optional["AgentObservabilityCallbackHandler"]] = ContextVar("active_callback", default=None)


# Cost mappings (in USD per 1M tokens)
PRICING = {
    "deepseek-chat": {"input": 0.28, "output": 1.00},
    "qwen-plus": {"input": 0.50, "output": 1.50},
    "qwen-turbo": {"input": 0.30, "output": 0.60},
    "qwen-max": {"input": 2.00, "output": 6.00},
}

class AgentObservabilityCallbackHandler(BaseCallbackHandler):
    def __init__(self):
        self.run_id = str(uuid.uuid4())[:8]
        self.start_time = time.time()
        self.total_latency = 0.0
        self.total_cost = 0.0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        
        self.llm_runs: List[Dict[str, Any]] = []
        self.tool_runs: List[Dict[str, Any]] = []
        
        # Temp state to track active runs
        self._active_llms: Dict[str, Dict[str, Any]] = {}
        self._active_tools: Dict[str, Dict[str, Any]] = {}

    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], run_id: uuid.UUID, **kwargs) -> None:
        model_name = serialized.get("kwargs", {}).get("model_name") or "unknown"
        self._active_llms[str(run_id)] = {
            "model_name": model_name,
            "prompts": prompts,
            "start_time": time.time(),
        }

    def on_llm_end(self, response: LLMResult, run_id: uuid.UUID, **kwargs) -> None:
        run_info = self._active_llms.pop(str(run_id), None)
        if not run_info:
            return
            
        duration = time.time() - run_info["start_time"]
        model_name = run_info["model_name"]
        
        # Extract tokens
        prompt_tokens = 0
        completion_tokens = 0
        
        if response.llm_output and "token_usage" in response.llm_output:
            usage = response.llm_output["token_usage"]
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
        elif response.generations and response.generations[0]:
            gen = response.generations[0][0]
            if hasattr(gen, "message") and gen.message:
                if hasattr(gen.message, "usage_metadata") and gen.message.usage_metadata:
                    usage = gen.message.usage_metadata
                    prompt_tokens = usage.get("input_tokens", 0)
                    completion_tokens = usage.get("output_tokens", 0)
                elif hasattr(gen.message, "response_metadata") and gen.message.response_metadata:
                    meta = gen.message.response_metadata
                    if "token_usage" in meta:
                        usage = meta["token_usage"]
                        prompt_tokens = usage.get("prompt_tokens", 0)
                        completion_tokens = usage.get("completion_tokens", 0)

        # Calculate cost
        rates = PRICING.get("qwen-plus") # default
        for key, val in PRICING.items():
            if key in model_name:
                rates = val
                break
        
        cost = ((prompt_tokens * rates["input"]) + (completion_tokens * rates["output"])) / 1000000.0
        
        self.total_input_tokens += prompt_tokens
        self.total_output_tokens += completion_tokens
        self.total_cost += cost
        
        output_text = ""
        if response.generations and response.generations[0]:
            output_text = response.generations[0][0].text
            
        self.llm_runs.append({
            "model_name": model_name,
            "duration": duration,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost": cost,
            "prompts": run_info["prompts"],
            "output": output_text
        })

    def on_llm_error(self, error: BaseException, run_id: uuid.UUID, **kwargs) -> None:
        run_info = self._active_llms.pop(str(run_id), None)
        if run_info:
            self.llm_runs.append({
                "model_name": run_info["model_name"],
                "duration": time.time() - run_info["start_time"],
                "error": str(error),
                "prompts": run_info["prompts"],
                "output": ""
            })

    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, run_id: uuid.UUID, **kwargs) -> None:
        tool_name = serialized.get("name") or "unknown"
        self._active_tools[str(run_id)] = {
            "name": tool_name,
            "input": input_str,
            "start_time": time.time(),
        }

    def on_tool_end(self, output: Any, run_id: uuid.UUID, **kwargs) -> None:
        tool_info = self._active_tools.pop(str(run_id), None)
        if not tool_info:
            return
        duration = time.time() - tool_info["start_time"]
        self.tool_runs.append({
            "name": tool_info["name"],
            "input": tool_info["input"],
            "output": str(output),
            "duration": duration,
            "status": "success"
        })

    def on_tool_error(self, error: BaseException, run_id: uuid.UUID, **kwargs) -> None:
        tool_info = self._active_tools.pop(str(run_id), None)
        if not tool_info:
            return
        duration = time.time() - tool_info["start_time"]
        self.tool_runs.append({
            "name": tool_info["name"],
            "input": tool_info["input"],
            "output": str(error),
            "duration": duration,
            "status": "error"
        })

    def finalize_run(self, question: str, answer: str, question_type: Optional[str] = None) -> Dict[str, Any]:
        overall_latency = time.time() - self.start_time
        self.total_latency = overall_latency
        
        trace_data = {
            "run_id": self.run_id,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "question": question,
            "question_type": question_type,
            "answer": answer,
            "total_latency_seconds": overall_latency,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "total_cost_usd": self.total_cost,
            "llm_calls_count": len(self.llm_runs),
            "tool_calls_count": len(self.tool_runs),
            "llm_calls": self.llm_runs,
            "tool_calls": self.tool_runs
        }
        
        # 1. Write to raw JSONL traces
        os.makedirs("logs", exist_ok=True)
        with open("logs/agent_traces.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(trace_data, ensure_ascii=False) + "\n")
            
        # 2. Write to human-readable log
        with open("logs/agent.log", "a", encoding="utf-8") as f:
            f.write(f"\n==================== RUN {self.run_id} ====================\n")
            f.write(f"Time: {trace_data['timestamp']}\n")
            f.write(f"Question: {question}\n")
            if question_type:
                f.write(f"Question Type: {question_type}\n")
            f.write(f"Answer: {answer}\n")
            f.write(f"Summary: Latency={overall_latency:.2f}s | Tokens={trace_data['total_tokens']} (In={self.total_input_tokens}, Out={self.total_output_tokens}) | Cost=${self.total_cost:.6f} USD\n")
            f.write("LLM Calls:\n")
            for idx, run in enumerate(self.llm_runs):
                err = f" | Error: {run['error']}" if "error" in run else ""
                f.write(f"  [{idx+1}] {run['model_name']} | Latency: {run['duration']:.2f}s | In: {run.get('prompt_tokens', 0)}, Out: {run.get('completion_tokens', 0)} | Cost: ${run.get('cost', 0):.6f}{err}\n")
            if not self.tool_runs:
                f.write("Tool Calls: None\n")
            else:
                f.write("Tool Calls:\n")
                for idx, run in enumerate(self.tool_runs):
                    f.write(f"  [{idx+1}] {run['name']} | Input: {run['input']} | Duration: {run['duration']:.2f}s | Status: {run['status']}\n")
                    output_str = run.get('output', '')
                    try:
                        parsed_output = json.loads(output_str)
                        pretty_output = json.dumps(parsed_output, ensure_ascii=False, indent=2)
                        indented_output = "\n".join("      " + line for line in pretty_output.splitlines())
                        f.write(f"      Output (JSON):\n{indented_output}\n")
                    except Exception:
                        indented_output = "\n".join("      " + line for line in output_str.splitlines())
                        f.write(f"      Output (Raw):\n{indented_output}\n")
            f.write(f"==========================================================\n")
            
        # 3. Print a premium ASCII dashboard to stdout (console)
        print("\n" + "╔" + "═" * 58 + "╗")
        print(f"║ 📊 三国志 AI 幕僚系统全链路追踪 [Run ID: {self.run_id}] ║")
        print("╠" + "═" * 58 + "╣")
        print(f"║ 提问: {question[:45] + '...' if len(question) > 45 else question:<45} ║")
        if question_type:
            print(f"║ Question Type: {question_type:<41} ║")
        print(f"║ 总耗时: {overall_latency:5.2f} 秒                                       ║")
        print(f"║ 总 Token: {trace_data['total_tokens']:<6} (输入: {self.total_input_tokens:<5} | 输出: {self.total_output_tokens:<5})             ║")
        print(f"║ 总成本: ${self.total_cost:8.6f} USD                                ║")
        print(f"║ 核心步骤数: LLM 阶段: {len(self.llm_runs):<2} | 工具调用: {len(self.tool_runs):<2}                    ║")
        if self.tool_runs:
            print("╟" + "─" * 58 + "╢")
            print("║ 🛠️ 工具使用详情:                                          ║")
            for idx, run in enumerate(self.tool_runs):
                tool_line = f"  • [{idx+1}] {run['name']} ({run['status']}) - {run['duration']:.2f}s"
                print(f"║ {tool_line:<56} ║")
        print("╚" + "═" * 58 + "╝\n")

        return trace_data
