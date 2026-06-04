import os
import asyncio
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import HumanMessage

load_dotenv()

class TestAsyncCallbackHandler(AsyncCallbackHandler):
    async def on_llm_start(self, serialized, prompts, **kwargs):
        print("▶️ LLM Async Start Callback")
        
    async def on_llm_end(self, response, **kwargs):
        print("⏹️ LLM Async End Callback")
        print(f"Response llm_output: {response.llm_output}")

async def test_stream():
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    # Tell LangChain to ask OpenAI/DashScope to return token usage in streaming
    llm = ChatOpenAI(
        model="qwen-plus",
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        stream_usage=True # Crucial flag for OpenAI compatible providers to stream usage!
    )
    
    handler = TestAsyncCallbackHandler()
    async for chunk in llm.astream([HumanMessage(content="你好，用五个字回答")], config={"callbacks": [handler]}):
        pass

if __name__ == "__main__":
    asyncio.run(test_stream())
