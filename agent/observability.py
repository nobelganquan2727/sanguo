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

active_callback_var: ContextVar[Optional[CallbackHandler]] = ContextVar("active_callback", default=None)

# Alias the old handler name to Langfuse's CallbackHandler to maintain backward compatibility for imports
AgentObservabilityCallbackHandler = CallbackHandler
