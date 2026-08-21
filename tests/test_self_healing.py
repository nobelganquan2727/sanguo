import os
import sys
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.qa_agent import ask_question, IntentAnalysis, DAGPlan, DAGPlanNoNeo4j, StateUpdate, TaskSpec
from agent.schemas import TaskSpecNoNeo4j


def _mock_llm_with_plans(intent, no_neo4j_plan, neo4j_plan, ainvoke_side_effect=None):
    mock_llm = MagicMock()

    def mock_with_structured_output(schema, **kwargs):
        m = MagicMock()
        if schema == IntentAnalysis:
            m.ainvoke = AsyncMock(return_value=intent)
        elif schema == DAGPlanNoNeo4j:
            m.ainvoke = AsyncMock(return_value=no_neo4j_plan)
        elif schema == DAGPlan:
            m.ainvoke = AsyncMock(return_value=neo4j_plan)
        else:
            m.ainvoke = AsyncMock(return_value=StateUpdate())
        return m

    mock_llm.with_structured_output.side_effect = mock_with_structured_output
    if ainvoke_side_effect is not None:
        mock_llm.ainvoke = AsyncMock(side_effect=ainvoke_side_effect)
    else:
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="GOOD CYPHER"))

    async def mock_astream(*args, **kwargs):
        chunk = MagicMock()
        chunk.content = "根据正史记载，检索完成。"
        yield chunk

    mock_llm.astream = mock_astream
    return mock_llm


class TestSelfHealing(unittest.TestCase):

    @patch("agent.qa_agent.has_valid_db_records", return_value=True)
    @patch("agent.qa_agent.search_vector_graph_async")
    @patch("agent.qa_agent.save_cache")
    @patch("agent.qa_agent.lookup_cache")
    @patch("agent.tools.run_query")
    @patch("agent.tools.get_llm")
    @patch("agent.qa_agent.get_llm")
    def test_correction_success(
        self,
        mock_get_llm,
        mock_tools_get_llm,
        mock_run_query,
        mock_lookup,
        mock_save,
        mock_vector,
        mock_has_valid,
    ):
        mock_lookup.return_value = (None, None, 0.0)
        mock_vector.ainvoke = AsyncMock(return_value='[{"title": "刘备臧霸", "year": 200}]')

        intent = IntentAnalysis(
            type="complex",
            rewritten_question="刘备和臧霸有什么关系？",
            entities=["刘备", "臧霸"],
        )
        first_plan = DAGPlanNoNeo4j(
            thought="first turn uses dedicated tools",
            tasks=[
                TaskSpecNoNeo4j(
                    id="vector_task",
                    tool="search_vector_graph_async",
                    args={"query": "刘备 臧霸", "k": 5},
                    dependencies=[],
                )
            ],
        )
        neo4j_plan = DAGPlan(
            thought="test cypher correction",
            tasks=[
                TaskSpec(
                    id="cypher_task",
                    tool="query_neo4j_async",
                    args={"cypher": "BAD CYPHER"},
                    dependencies=[],
                )
            ],
        )
        done_plan = DAGPlan(thought="enough facts", tasks=[], is_finished=True)
        neo4j_returns = iter([neo4j_plan, done_plan])

        mock_llm = _mock_llm_with_plans(intent, first_plan, neo4j_plan)
        # Second DAGPlan call (turn 2) must stop the loop after one Cypher repair
        def mock_with_structured_output(schema, **kwargs):
            m = MagicMock()
            if schema == IntentAnalysis:
                m.ainvoke = AsyncMock(return_value=intent)
            elif schema == DAGPlanNoNeo4j:
                m.ainvoke = AsyncMock(return_value=first_plan)
            elif schema == DAGPlan:
                m.ainvoke = AsyncMock(side_effect=lambda *a, **k: next(neo4j_returns))
            else:
                m.ainvoke = AsyncMock(return_value=StateUpdate())
            return m

        mock_llm.with_structured_output.side_effect = mock_with_structured_output
        mock_get_llm.return_value = mock_llm
        mock_tools_get_llm.return_value = mock_llm

        mock_run_query.side_effect = [
            Exception("Syntax error near 'MATCH' in Cypher"),
            [{"direct_events": [], "shared_persons": [], "shared_locations": [], "p1_events": [], "p2_events": []}],
        ]

        print("\n=== Running self-healing success test ===")
        ans = ask_question("刘备和臧霸有什么关系？")
        print("Answer obtained:")
        print(ans)

        self.assertEqual(mock_run_query.call_count, 2)
        self.assertTrue(mock_get_llm.called)
        self.assertTrue(ans)

    @patch("agent.qa_agent.has_valid_db_records", return_value=True)
    @patch("agent.qa_agent.search_vector_graph_async")
    @patch("agent.qa_agent.save_cache")
    @patch("agent.qa_agent.lookup_cache")
    @patch("agent.tools.run_query")
    @patch("agent.tools.get_llm")
    @patch("agent.qa_agent.get_llm")
    def test_graceful_degradation(
        self,
        mock_get_llm,
        mock_tools_get_llm,
        mock_run_query,
        mock_lookup,
        mock_save,
        mock_vector,
        mock_has_valid,
    ):
        mock_lookup.return_value = (None, None, 0.0)
        mock_vector.ainvoke = AsyncMock(return_value='[{"title": "徐晃", "year": 196}]')

        intent = IntentAnalysis(
            type="complex",
            rewritten_question="徐晃最开始效力于谁？",
            entities=["徐晃"],
        )
        first_plan = DAGPlanNoNeo4j(
            thought="first turn uses dedicated tools",
            tasks=[
                TaskSpecNoNeo4j(
                    id="vector_task",
                    tool="search_vector_graph_async",
                    args={"query": "徐晃", "k": 5},
                    dependencies=[],
                )
            ],
        )
        neo4j_plan = DAGPlan(
            thought="test graceful degradation",
            tasks=[
                TaskSpec(
                    id="cypher_task",
                    tool="query_neo4j_async",
                    args={"cypher": "BAD CYPHER"},
                    dependencies=[],
                )
            ],
        )
        done_plan = DAGPlan(thought="enough facts", tasks=[], is_finished=True)
        neo4j_returns = iter([neo4j_plan, done_plan])

        mock_llm = MagicMock()

        def mock_with_structured_output(schema, **kwargs):
            m = MagicMock()
            if schema == IntentAnalysis:
                m.ainvoke = AsyncMock(return_value=intent)
            elif schema == DAGPlanNoNeo4j:
                m.ainvoke = AsyncMock(return_value=first_plan)
            elif schema == DAGPlan:
                m.ainvoke = AsyncMock(side_effect=lambda *a, **k: next(neo4j_returns))
            else:
                m.ainvoke = AsyncMock(return_value=StateUpdate())
            return m

        mock_llm.with_structured_output.side_effect = mock_with_structured_output
        mock_llm.ainvoke = AsyncMock(side_effect=[
            MagicMock(content="BAD CYPHER 2"),
            MagicMock(content="BAD CYPHER 3"),
        ])

        async def mock_astream(*args, **kwargs):
            chunk = MagicMock()
            chunk.content = "根据正史记载，检索完成。"
            yield chunk

        mock_llm.astream = mock_astream
        mock_get_llm.return_value = mock_llm
        mock_tools_get_llm.return_value = mock_llm

        mock_run_query.side_effect = Exception("Database connection lost permanently")

        print("\n=== Running graceful degradation test ===")
        ans = ask_question("徐晃最开始效力于谁？")
        print("Answer obtained:")
        print(ans)

        self.assertEqual(mock_run_query.call_count, 3)
        self.assertTrue(ans)


if __name__ == "__main__":
    unittest.main()
