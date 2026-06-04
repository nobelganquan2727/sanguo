import os
from pydantic import BaseModel, Field
from typing import List, Literal
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

class TestIntent(BaseModel):
    category: Literal["a", "b"] = Field(description="category selection")
    entities: List[str] = Field(description="entities list")

def test_structure():
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    llm = ChatOpenAI(
        model="qwen-plus",
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    
    structured_llm = llm.with_structured_output(TestIntent, method="function_calling")
    
    try:
        res = structured_llm.invoke("提取曹操和刘备，类别选 a")
        print(f"✅ Success! Category: {res.category}, Entities: {res.entities}")
    except Exception as e:
        print(f"❌ Failed structure test: {e}")

if __name__ == "__main__":
    test_structure()
