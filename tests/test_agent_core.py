import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from unittest.mock import patch, MagicMock
from agent.qa_agent import ask_question, IntentAnalysis

class TestAgentCore(unittest.TestCase):
    
    @patch('agent.qa_agent.save_cache')
    @patch('agent.qa_agent.lookup_cache')
    @patch('agent.qa_agent.run_query')
    @patch('agent.qa_agent.get_llm')
    def test_memory_summarization_triggers(self, mock_get_llm, mock_run_query, mock_lookup, mock_save):
        mock_lookup.return_value = (None, 0.0)
        
        # Create a mock LLM instance
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm
        
        # Mock answers for different steps
        # Step 1: Memory summary (returns a summary string)
        # Step 2: Intent analysis structured output (returns IntentAnalysis)
        # Step 3: Agent loop invocation (returns an AIMessage with no tool calls)
        # Step 4: Final answer synthesis (returns AIMessage)
        mock_summary_res = MagicMock()
        mock_summary_res.content = "曹操与刘备在许昌联合，后来刘备参与衣带诏阴谋。"
        
        mock_intent_analysis = IntentAnalysis(
            type="fact",
            rewritten_question="刘备逃离许都后去了哪里？",
            entities=["刘备", "许都"]
        )
        
        mock_agent_response = MagicMock()
        mock_agent_response.tool_calls = []
        mock_agent_response.content = "Agent decided to stop."
        
        mock_synthesis_res = MagicMock()
        mock_synthesis_res.content = "老夫查阅三国史实，刘备在建安五年东奔徐州。"
        
        # Setting up the side effect of LLM calls
        # 1st call: llm.invoke(summary_prompt) -> mock_summary_res
        # 2nd call: llm.with_structured_output -> mock_structured_llm.invoke() -> mock_intent_analysis
        # 3rd call: llm.bind_tools().invoke() -> mock_agent_response
        # 4th call: llm.invoke(synthesis_prompt) -> mock_synthesis_res
        
        mock_structured_llm = MagicMock()
        mock_structured_llm.invoke.return_value = mock_intent_analysis
        mock_llm.with_structured_output.return_value = mock_structured_llm
        
        mock_llm_with_tools = MagicMock()
        mock_llm_with_tools.invoke.return_value = mock_agent_response
        mock_llm.bind_tools.return_value = mock_llm_with_tools
        
        mock_llm.invoke.side_effect = [mock_summary_res, mock_synthesis_res]
        
        # Conversation history longer than 6 messages (each message dict is a turn step)
        history = [
            {"role": "user", "content": "你好，曹操在哪里？"},
            {"role": "assistant", "content": "曹操当时在许都。"},
            {"role": "user", "content": "那刘备呢？"},
            {"role": "assistant", "content": "刘备也在许都依附曹操。"},
            {"role": "user", "content": "他们发生了什么？"},
            {"role": "assistant", "content": "曹操与刘备煮酒论英雄。"},
            {"role": "user", "content": "刘备参与了衣带诏吗？"},
            {"role": "assistant", "content": "是的，刘备参与了董承的衣带诏阴谋。"},
            {"role": "user", "content": "那他后来逃往哪里了？"} # Pronoun "他" should be resolved to "刘备"
        ]
        
        print("\n=== Running Memory Summarization and Pronoun Resolution Test ===")
        ans = ask_question("那他后来逃往哪里了？", history=history)
        print("Answer obtained:")
        print(ans)
        
        # Verify memory summary was invoked
        self.assertTrue(mock_llm.invoke.called)
        # Verify with_structured_output was configured and invoked
        mock_llm.with_structured_output.assert_called_with(IntentAnalysis, method="function_calling")
        # Verify the answer
        self.assertEqual(ans, "老夫查阅三国史实，刘备在建安五年东奔徐州。")
 
    @patch('agent.qa_agent.save_cache')
    @patch('agent.qa_agent.lookup_cache')
    @patch('agent.qa_agent.run_query')
    @patch('agent.qa_agent.get_llm')
    def test_complex_planning_flow(self, mock_get_llm, mock_run_query, mock_lookup, mock_save):
        mock_lookup.return_value = (None, 0.0)
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm
        
        # Mocking complex planning split
        # Step 1: Intent Analysis -> complex_planning
        mock_intent_analysis = IntentAnalysis(
            type="complex_planning",
            rewritten_question="分析曹操在官渡之战前后的战略调整",
            entities=["曹操", "官渡之战"]
        )
        mock_structured_llm = MagicMock()
        mock_structured_llm.invoke.return_value = mock_intent_analysis
        mock_llm.with_structured_output.return_value = mock_structured_llm
        
        # Step 2: Planning prompt -> decomposes into sub-queries
        mock_planning_res = MagicMock()
        mock_planning_res.content = '{"sub_queries": ["曹操官渡之战前的部署", "曹操官渡之战中的抉择", "曹操官渡之战后的动作"]}'
        
        # Step 3: Tool-calling loops for each of the 3 sub-queries
        mock_agent_response = MagicMock()
        mock_agent_response.tool_calls = [] # Agent decides no tools are needed for simplicity of test
        
        mock_llm_with_tools = MagicMock()
        mock_llm_with_tools.invoke.return_value = mock_agent_response
        mock_llm.bind_tools.return_value = mock_llm_with_tools
        
        # Step 4: Final synthesis
        mock_synthesis_res = MagicMock()
        mock_synthesis_res.content = "一、战前部署：曹操表引袁绍... 二、战中抉择... 三、战后影响..."
        
        # Order of invoke calls to mock_llm:
        # 1. invoke() for planning prompt -> mock_planning_res
        # 2. invoke() for final answer synthesis -> mock_synthesis_res
        mock_llm.invoke.side_effect = [mock_planning_res, mock_synthesis_res]
        
        print("\n=== Running Complex Planning Flow Test ===")
        ans = ask_question("分析曹操在官渡之战前后的战略调整")
        print("Answer obtained:")
        print(ans)
        
        # Assertions
        # Since there are 3 sub-queries and no tools are actually called, mock_llm_with_tools.invoke should be called 3 times
        self.assertEqual(mock_llm_with_tools.invoke.call_count, 3)
        self.assertIn("战前部署", ans)
 
if __name__ == '__main__':
    unittest.main()
