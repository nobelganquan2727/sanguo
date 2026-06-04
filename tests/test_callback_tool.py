import os
from dotenv import load_dotenv
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tools import tool

load_dotenv()

class TestToolCallbackHandler(BaseCallbackHandler):
    def on_tool_start(self, serialized, input_str, **kwargs):
        print(f"🛠️ Tool Start: {serialized.get('name') or 'unknown'} with input: {input_str}")
        
    def on_tool_end(self, output, **kwargs):
        print(f"🛠️ Tool End: output length {len(str(output))}")

@tool
def my_dummy_tool(val: str) -> str:
    """A dummy test tool."""
    return f"Processed {val}"

def test_tool():
    handler = TestToolCallbackHandler()
    my_dummy_tool.invoke({"val": "hello"}, config={"callbacks": [handler]})

if __name__ == "__main__":
    test_tool()
