import os
import sys
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.qa_agent import ask_question, IntentAnalysis

class TestSelfHealing(unittest.TestCase):
    
    @patch('agent.qa_agent.save_cache')
    @patch('agent.qa_agent.lookup_cache')
    @patch('agent.tools.run_query')
    @patch('agent.qa_agent.get_llm')
    def test_correction_success(self, mock_get_llm, mock_run_query, mock_lookup, mock_save):
        mock_lookup.return_value = (None, 0.0)
        
        # Mock LLM
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm
        
        # 1. Intent analysis structured output
        mock_intent_analysis = IntentAnalysis(
            type="relationship",
            rewritten_question="刘备和臧霸有什么关系？",
            entities=["刘备", "臧霸"]
        )
        mock_structured_llm = MagicMock()
        mock_structured_llm.ainvoke = AsyncMock(return_value=mock_intent_analysis)
        mock_llm.with_structured_output.return_value = mock_structured_llm
        
        # 2. Agent Step 1 tool-calling (calls query_neo4j)
        mock_agent_response = MagicMock()
        mock_agent_response.tool_calls = [{"name": "query_neo4j_async", "args": {"cypher": "BAD CYPHER"}, "id": "call_1"}]
        mock_agent_response.content = "I need to check neo4j."
        
        mock_llm_with_tools = MagicMock()
        # Step 1 returns tool calls, Step 2 returns stop
        mock_agent_stop_response = MagicMock()
        mock_agent_stop_response.tool_calls = []
        mock_agent_stop_response.content = "Stop."
        mock_llm_with_tools.ainvoke = AsyncMock(side_effect=[mock_agent_response, mock_agent_stop_response])
        mock_llm.bind_tools.return_value = mock_llm_with_tools
        
        # 3. Cypher self-correction inside query_neo4j tool
        # Inside query_neo4j, get_llm() is called and returns mock_llm, then mock_llm.invoke(execution_messages) is called
        mock_correction_res = MagicMock()
        mock_correction_res.content = "GOOD CYPHER"
        
        # Final synthesis
        mock_synthesis_res = MagicMock()
        mock_synthesis_res.content = "根据正史记载，刘备与臧霸关系如下..."
        
        mock_llm.ainvoke = AsyncMock(side_effect=[mock_correction_res, mock_synthesis_res])
        
        # Mock run_query: first call fails (syntax error), second call succeeds
        mock_run_query.side_effect = [
            Exception("Syntax error near 'MATCH' in Cypher"),
            [{"direct_events": [], "shared_persons": [], "shared_locations": [], "p1_events": [], "p2_events": []}]
        ]
        
        print("\n=== Running self-healing success test ===")
        ans = ask_question("刘备和臧霸有什么关系？")
        print("Answer obtained:")
        print(ans)
        
        # Verify run_query was called twice (initial + 1 retry)
        self.assertEqual(mock_run_query.call_count, 2)
        # Verify get_llm was called
        self.assertTrue(mock_get_llm.called)
        
    @patch('agent.qa_agent.save_cache')
    @patch('agent.qa_agent.lookup_cache')
    @patch('agent.tools.run_query')
    @patch('agent.qa_agent.get_llm')
    def test_graceful_degradation(self, mock_get_llm, mock_run_query, mock_lookup, mock_save):
        mock_lookup.return_value = (None, 0.0)
        
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm
        
        # Intent analysis structured output
        mock_intent_analysis = IntentAnalysis(
            type="fact",
            rewritten_question="徐晃最开始效力于谁？",
            entities=["徐晃"]
        )
        mock_structured_llm = MagicMock()
        mock_structured_llm.ainvoke = AsyncMock(return_value=mock_intent_analysis)
        mock_llm.with_structured_output.return_value = mock_structured_llm
        
        # Agent Step 1 tool-calling (calls query_neo4j)
        mock_agent_response = MagicMock()
        mock_agent_response.tool_calls = [{"name": "query_neo4j_async", "args": {"cypher": "BAD CYPHER"}, "id": "call_1"}]
        mock_agent_response.content = "Checking neo4j."
        
        mock_llm_with_tools = MagicMock()
        mock_agent_stop_response = MagicMock()
        mock_agent_stop_response.tool_calls = []
        mock_agent_stop_response.content = "Stop."
        mock_llm_with_tools.ainvoke = AsyncMock(side_effect=[mock_agent_response, mock_agent_stop_response])
        mock_llm.bind_tools.return_value = mock_llm_with_tools
        
        # Correction calls in query_neo4j (fails up to max_retries = 2, so 2 correction LLM calls)
        mock_corr_1 = MagicMock()
        mock_corr_1.content = "BAD CYPHER 2"
        mock_corr_2 = MagicMock()
        mock_corr_2.content = "BAD CYPHER 3"
        
        # Final synthesis
        mock_synthesis_res = MagicMock()
        mock_synthesis_res.content = "由于藏书阁故障，但依据正史徐晃起初效力于杨奉..."
        
        mock_llm.ainvoke = AsyncMock(side_effect=[mock_corr_1, mock_corr_2, mock_synthesis_res])
        
        # All run_query calls fail (initial + 2 retries = 3 calls)
        mock_run_query.side_effect = Exception("Database connection lost permanently")
        
        print("\n=== Running graceful degradation test ===")
        ans = ask_question("徐晃最开始效力于谁？")
        print("Answer obtained:")
        print(ans)
        
        # Verify run_query was called 3 times (initial + 2 retries)
        self.assertEqual(mock_run_query.call_count, 3)
 
if __name__ == '__main__':
    unittest.main()
