import sys
import types

# 1. Alias LangChain legacy import paths to LangChain Core in memory to support Langfuse SDK v2
def make_dummy_module(name, attrs):
    mod = types.ModuleType(name)
    mod.__path__ = []
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod

if 'langchain.callbacks' not in sys.modules:
    import langchain_core.callbacks.base
    make_dummy_module('langchain.callbacks', {})
    make_dummy_module('langchain.callbacks.base', {'BaseCallbackHandler': langchain_core.callbacks.base.BaseCallbackHandler})

if 'langchain.schema' not in sys.modules:
    import langchain_core.agents
    import langchain_core.messages
    import langchain_core.outputs
    import langchain_core.documents

    make_dummy_module('langchain.schema', {})
    make_dummy_module('langchain.schema.agent', {
        'AgentAction': langchain_core.agents.AgentAction,
        'AgentFinish': langchain_core.agents.AgentFinish
    })
    make_dummy_module('langchain.schema.messages', {
        'BaseMessage': langchain_core.messages.BaseMessage
    })
    make_dummy_module('langchain.schema.output', {
        'LLMResult': langchain_core.outputs.LLMResult
    })
    make_dummy_module('langchain.schema.document', {
        'Document': langchain_core.documents.Document
    })

# 2. Import CallbackHandler from langfuse.callback
from langfuse.callback import CallbackHandler
from contextvars import ContextVar
from typing import Optional
import logging

# Filter out the annoying Langfuse internal callback exceptions (such as "run not found" or "parent run not found")
# which are caught internally in Langfuse and printed via self.log.exception(e) rather than raised.
class LangfuseErrorFilter(logging.Filter):
    def filter(self, record):
        if record.exc_info:
            _, exc_value, _ = record.exc_info
            if exc_value and ("run not found" in str(exc_value) or "parent run not found" in str(exc_value)):
                return False
        msg = str(record.msg)
        if "run not found" in msg or "parent run not found" in msg:
            return False
        return True

logging.getLogger("langfuse").addFilter(LangfuseErrorFilter())

# Monkeypatch Langfuse CallbackHandler to catch and swallow LangChain callback errors (e.g., "run not found")
def _safe_callback_wrapper(original_method):
    def wrapper(self, *args, **kwargs):
        try:
            return original_method(self, *args, **kwargs)
        except Exception as e:
            print(f"⚠️ [Observability] Swallowed Langfuse callback exception: {e}", file=sys.stderr)
            return None
    return wrapper

for attr_name in dir(CallbackHandler):
    if attr_name.startswith("on_"):
        attr_value = getattr(CallbackHandler, attr_name)
        if callable(attr_value) and not isinstance(attr_value, type):
            setattr(CallbackHandler, attr_name, _safe_callback_wrapper(attr_value))

active_callback_var: ContextVar[Optional[CallbackHandler]] = ContextVar("active_callback", default=None)
