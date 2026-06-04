import os
import time
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage

load_dotenv()

class TestCallbackHandler(BaseCallbackHandler):
    def on_llm_start(self, serialized, prompts, **kwargs):
        self.start_time = time.time()
        print("▶️ LLM Start Callback triggered")
        
    def on_llm_end(self, response, **kwargs):
        duration = time.time() - self.start_time
        print(f"⏹️ LLM End Callback triggered. Duration: {duration:.2f}s")
        print(f"Response llm_output: {response.llm_output}")
        if response.generations and response.generations[0]:
            gen = response.generations[0][0]
            print(f"Generation Info: {gen.generation_info}")

def test_callback():
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    llm = ChatOpenAI(
        model="qwen-plus",
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    
    handler = TestCallbackHandler()
    llm.invoke([HumanMessage(content="你好")], config={"callbacks": [handler]})

if __name__ == "__main__":
    test_callback()
