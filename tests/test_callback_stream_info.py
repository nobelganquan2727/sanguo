import os
import asyncio
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import HumanMessage

load_dotenv()

class TestAsyncCallbackHandler(AsyncCallbackHandler):
    async def on_llm_end(self, response, **kwargs):
        print("⏹️ LLM Async End Callback")
        print(f"Response: {response}")
        for gen_list in response.generations:
            for gen in gen_list:
                print(f"Gen message: {gen.message}")
                print(f"Gen info: {gen.generation_info}")

async def test_stream():
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    llm = ChatOpenAI(
        model="qwen-plus",
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_kwargs={"stream_options": {"include_usage": True}}
    )
    
    handler = TestAsyncCallbackHandler()
    async for chunk in llm.astream([HumanMessage(content="你好")], config={"callbacks": [handler]}):
        pass

if __name__ == "__main__":
    asyncio.run(test_stream())
