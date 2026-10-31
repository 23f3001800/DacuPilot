import unittest
from langchain_core.messages import HumanMessage, AIMessage

from datapilot.query_optimizer import (
    SessionQueryCache,
    optimize_session_query,
)


class SessionQueryOptimizerTests(unittest.TestCase):
    def test_standalone_question_preserves_intent_without_noise(self):
        q = "Can you please explain the annual leave entitlement for employees?"
        optimized = optimize_session_query(q, [])
        self.assertIn("annual leave entitlement for employees", optimized)
        self.assertNotIn("Can you please explain", optimized)

    def test_elliptical_follow_up_incorporates_recent_context(self):
        history = [
            HumanMessage(content="What is the policy for annual leave?"),
            AIMessage(content="Full-time employees receive 25 days."),
        ]
        q = "How many days carry over to next year?"
        optimized = optimize_session_query(q, history, active_topic="Leave and holidays")
        # Should carry forward annual leave context
        self.assertIn("leave", optimized.lower())
        self.assertIn("carry over", optimized.lower())

    def test_topic_grounding_used_when_history_sparse(self):
        q = "What is the penalty?"
        optimized = optimize_session_query(q, [], active_topic="Insurance and forms")
        self.assertIn("insurance", optimized.lower())

    def test_session_query_cache_hit_and_eviction(self):
        cache = SessionQueryCache(capacity_per_session=2)
        session_id = "test-session-123"

        cache.put(session_id, "What is annual leave?", {"answer": "25 days"})
        hit = cache.get(session_id, "What is annual leave?")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["answer"], "25 days")

        # Case and whitespace insensitivity
        hit_case = cache.get(session_id, "  what is annual leave?  ")
        self.assertIsNotNone(hit_case)

        # Cache miss
        miss = cache.get(session_id, "Different question?")
        self.assertIsNone(miss)

        # Clear session
        cache.clear_session(session_id)
        self.assertIsNone(cache.get(session_id, "What is annual leave?"))


if __name__ == "__main__":
    unittest.main()
