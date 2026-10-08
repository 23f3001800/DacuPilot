import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage

from document_assistance.core import document


class FakeLLM:
    def __init__(self):
        self.prompts = []
        self.history_sizes = []

    def invoke(self, messages):
        self.prompts.append(messages[0].content)
        self.history_sizes.append(len(messages))
        return AIMessage(
            content="Answer supported by the assignment. "
            "Source: [Questions.docx — Deliverables]"
        )


class ConversationTests(unittest.TestCase):
    def test_ten_turns_retain_context_and_cite_the_loaded_document(self):
        fake_llm = FakeLLM()
        questions = [
            "What should the Excel agent do?",
            "What should the support assistant remember?",
            "Which document fields need confidence scores?",
            "How are handwritten fields treated?",
            "What needs a human review flag?",
            "Which documents does the pipeline classify?",
            "What should the final JSON contain?",
            "How should the assistant cite sources?",
            "Can I ask another question about inventory?",
            "What is the OCR evaluation focus?",
        ]
        config = {"configurable": {"thread_id": "ten-turn-test"}}

        with patch.object(document, "get_llm", return_value=fake_llm):
            for question in questions:
                result = document.compiled_agent.invoke(
                    {"messages": [HumanMessage(content=question)]},
                    config=config,
                )
                self.assertIn(
                    "Source: [Questions.docx — Deliverables]",
                    result["messages"][-1].content,
                )

        state = document.compiled_agent.get_state(config).values
        self.assertEqual(len(state["messages"]), 20)
        self.assertEqual(len(fake_llm.prompts), 10)
        self.assertTrue(
            all("IFSC" in prompt for prompt in fake_llm.prompts)
        )
        self.assertIn("Acknowledge the change", fake_llm.prompts[1])
        self.assertIn("Avoid repeating prior explanations", fake_llm.prompts[0])


if __name__ == "__main__":
    unittest.main()
