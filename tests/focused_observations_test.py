import unittest

from src.accessibility import render_accessibility_tree
from src.controller.context import build_model_context
from src.models.execution import ExecutionResult
from src.models.observations import BrowserObservation
from src.models.state import AgentState


class FocusedObservationTest(unittest.TestCase):
    def test_main_content_precedes_navigation_and_outline_is_bounded(self):
        tree = {
            "nodes": [{
                "role": "WebArea",
                "children": [
                    {"role": "navigation", "children": [
                        {"role": "link", "name": "Search", "state": {
                            "url": "https://example.com/search?" + "x" * 2_000,
                        }},
                    ]},
                    {"role": "main", "children": [
                        {"role": "heading", "name": "Relevant result"},
                        *[{"role": "StaticText", "name": f"Other result {i}: " + "x" * 100}
                          for i in range(200)],
                    ]},
                ],
            }],
        }

        outline = render_accessibility_tree(tree)

        self.assertTrue(outline.startswith('main\n  heading "Relevant result"'))
        self.assertLessEqual(len(outline), 10_000)
        self.assertIn("[Page outline truncated", outline)
        self.assertNotIn("?" + "x" * 100, outline)

    def test_dialog_precedes_main_and_link_query_is_shortened(self):
        tree = {"nodes": [
            {"role": "main", "name": "Page content"},
            {"role": "dialog", "children": [
                {"role": "link", "name": "Continue", "state": {
                    "url": "https://example.com/next?tracking=" + "x" * 2_000,
                }},
            ]},
        ]}

        outline = render_accessibility_tree(tree)

        self.assertTrue(outline.startswith("dialog\n"))
        self.assertIn('url="https://example.com/next"', outline)
        self.assertNotIn("tracking=", outline)

    def test_execution_details_are_bounded_without_changing_saved_state(self):
        state = AgentState(
            task="Find a price",
            agent="mid",
            observation=BrowserObservation(
                url="https://example.com", title="Example",
                accessibility_tree={"nodes": []}, raw_node_count=0, kept_node_count=0,
            ),
            last_execution=ExecutionResult(
                success=True, result="r" * 5_000, stdout="s" * 5_000,
            ),
        )

        execution = build_model_context(state)["last_execution_result"]

        self.assertTrue(execution["result"].startswith("r" * 3_000))
        self.assertIn("[Truncated", execution["result"])
        self.assertTrue(execution["stdout"].startswith("s" * 3_000))
        self.assertEqual(len(state.last_execution.result), 5_000)
