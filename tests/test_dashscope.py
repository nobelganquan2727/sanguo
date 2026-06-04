import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

def test_dashscope():
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        print("❌ DASHSCOPE_API_KEY not found in environment!")
        return
    
    print(f"Key found: {api_key[:6]}...")
    
    # Test qwen-turbo or qwen-plus via compatible endpoint
    llm = ChatOpenAI(
        model="qwen-plus",
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    
    try:
        res = llm.invoke("你好，请问你是谁？用五个字回答。")
        print(f"✅ Success! Response: {res.content}")
    except Exception as e:
        print(f"❌ Failed to query DashScope: {e}")

if __name__ == "__main__":
    test_dashscope()
