import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from agent.utils import evaluate_expression
from services.event_service import build_events_query


class TestEvaluateExpression(unittest.TestCase):
    def test_passthrough(self):
        self.assertEqual(evaluate_expression("曹操", {}), "曹操")

    def test_placeholder_and_add(self):
        raw = {"t1": [{"year": 211}]}
        self.assertEqual(evaluate_expression("{{t1.output.year}} + 5", raw), 216)

    def test_placeholder_subtract(self):
        raw = {"t1": {"year": 220}}
        self.assertEqual(evaluate_expression("{{t1.output.year}} - 2", raw), 218)


class TestBuildEventsQuery(unittest.TestCase):
    def test_user_input_is_parameterized(self):
        cypher, params = build_events_query(
            start=190,
            end=195,
            person_include="曹操' OR 1=1 --",
            person_exclude="刘备",
            location="许县",
            event_type="军事征伐",
        )
        self.assertNotIn("曹操' OR 1=1 --", cypher)
        self.assertNotIn("'许县'", cypher)
        self.assertNotIn("'军事征伐'", cypher)
        self.assertEqual(params["pinc_0"], "曹操' OR 1=1 --")
        self.assertEqual(params["pex_0"], "刘备")
        self.assertEqual(params["location"], "许县")
        self.assertEqual(params["event_type"], "军事征伐")
        self.assertIn("$pinc_0", cypher)
        self.assertIn("$location", cypher)
        self.assertIn("SKIP $offset", cypher)
        self.assertIn("LIMIT $limit", cypher)

    def test_biography_names_use_list_param(self):
        cypher, params = build_events_query(
            start=180, end=280, person_include="曹操, 刘备", biography_only=True
        )
        self.assertEqual(params["bio_names"], ["曹操", "刘备"])
        self.assertIn("$bio_names", cypher)
        self.assertNotIn("'曹操'", cypher)


if __name__ == "__main__":
    unittest.main()
