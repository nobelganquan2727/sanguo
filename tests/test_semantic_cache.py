import os
import sys
import unittest
import json
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.cache import cosine_similarity, lookup_cache, save_cache, CACHE_FILE
from agent.tools import truncate_tool_output
from agent.qa_agent import ask_question

class TestSemanticCache(unittest.TestCase):
    
    def setUp(self):
        # Backup existing cache file if any
        self.backup_existed = os.path.exists(CACHE_FILE)
        if self.backup_existed:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                self.backup_content = f.read()
            os.remove(CACHE_FILE)

    def tearDown(self):
        # Restore cache file
        if os.path.exists(CACHE_FILE):
            os.remove(CACHE_FILE)
        if self.backup_existed:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                f.write(self.backup_content)

    def test_cosine_similarity(self):
        v1 = [1.0, 0.0, 0.0]
        v2 = [1.0, 0.0, 0.0]
        v3 = [0.0, 1.0, 0.0]
        v4 = [1.0, 1.0, 0.0]
        
        self.assertAlmostEqual(cosine_similarity(v1, v2), 1.0)
        self.assertAlmostEqual(cosine_similarity(v1, v3), 0.0)
        self.assertAlmostEqual(cosine_similarity(v1, v4), 1.0 / (1.0 * 1.41421356), places=5)

    @patch("agent.cache.get_bge_m3_embedding")
    def test_cache_save_and_lookup(self, mock_embedding):
        # We will mock the vectors returned by DashScope
        # "曹操" and "阿瞒" will have very high similarity
        # "诸葛亮" will have low similarity
        vectors = {
            "曹操是谁？": [1.0, 0.1, 0.0],
            "阿瞒是谁？": [0.99, 0.12, 0.0],
            "诸葛亮是谁？": [0.0, 0.9, 0.2]
        }
        mock_embedding.side_effect = lambda text: vectors.get(text, [0.0, 0.0, 0.0])
        
        # Initially, cache lookup should miss
        ans, sim = lookup_cache("曹操是谁？")
        self.assertIsNone(ans)
        
        # Save a reply
        save_cache("曹操是谁？", "魏武帝曹操，字孟德。")
        
        # Exact lookup should hit
        ans, sim = lookup_cache("曹操是谁？")
        self.assertEqual(ans, "魏武帝曹操，字孟德。")
        self.assertAlmostEqual(sim, 1.0)
        
        # Similar lookup should hit
        ans, sim = lookup_cache("阿瞒是谁？")
        self.assertEqual(ans, "魏武帝曹操，字孟德。")
        self.assertTrue(sim > 0.92)
        
        # Unrelated lookup should miss
        ans, sim = lookup_cache("诸葛亮是谁？")
        self.assertIsNone(ans)
        self.assertTrue(sim < 0.92)

    def test_truncate_tool_output(self):
        short_text = "This is a short text."
        long_text = "A" * 9000
        
        truncated_short = truncate_tool_output(short_text, max_chars=3000)
        truncated_long = truncate_tool_output(long_text, max_chars=3000)
        
        self.assertEqual(truncated_short, short_text)
        self.assertEqual(len(truncated_long), 3000 + len("\n\n【卷宗纪要说明】此处史料文字过长已作删减，仅展示前文3000字。"))
        self.assertTrue("已作删减" in truncated_long)
        self.assertTrue(truncated_long.startswith("A" * 3000))

    @patch("agent.qa_agent.lookup_cache")
    def test_ask_question_hits_cache(self, mock_lookup):
        mock_lookup.return_value = ("魏武帝曹操，字孟德。", 0.98)
        
        # Call ask_question, it should return the cached answer immediately
        # without running any LLM logic
        ans = ask_question("曹操是谁？")
        self.assertEqual(ans, "魏武帝曹操，字孟德。")
        mock_lookup.assert_called_with("曹操是谁？")

if __name__ == "__main__":
    unittest.main()
