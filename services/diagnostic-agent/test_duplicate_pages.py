"""Offline real agent calls distinguish duplicate attempts from unique page delivery."""
import asyncio
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

spec = importlib.util.spec_from_file_location("duplicate_page_runner", Path(__file__).with_name("runner.py"))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def payload():
    return {"config": {"model": "offline", "api_key": "synthetic", "base_url": "https://synthetic.invalid"},
            "text": "current", "evidence": [{"reference": "FILE-current", "title": "current.log", "content": "unique evidence page"}],
            "references": []}


def tool(data):
    return runner.create_agent(None, data)._function_toolset.tools["read_evidence"].function


class DuplicatePageTests(unittest.TestCase):
    def test_real_agent_receives_first_page_then_explicit_repeat_metadata(self):
        data = payload()
        seen = []

        def respond(messages, info):
            seen.append(messages)
            if len(seen) <= 3:
                return ModelResponse(parts=[ToolCallPart("read_evidence", {"references": ["FILE-current"], "offset": 0, "length": 6000})])
            return ModelResponse(parts=[ToolCallPart("final_result", {
                "answer": "Current evidence only", "suggested_actions": [], "verification_steps": [], "citations": ["FILE-current"],
            })])

        with patch.object(runner, "OpenAIProvider"), patch.object(runner, "OpenAIChatModel", return_value=FunctionModel(respond)):
            result = asyncio.run(runner.analyze(data))
        trace = result["evidence_trace"]
        self.assertEqual(len(seen), 4)
        self.assertEqual(len(trace["reads"]), 1)
        self.assertEqual(len(data["_read_pages"]), 1)
        self.assertEqual(len(trace["read_attempts"]), 3)
        self.assertEqual([row["status"] for row in trace["read_attempts"]], ["read", "already_read", "already_read"])
        self.assertTrue(all(row["first_read_index"] == 0 for row in trace["read_attempts"]))
        self.assertNotIn("unique evidence page", json.dumps(trace))
        self.assertEqual({row["sha256"] for row in trace["read_attempts"]},
                         {hashlib.sha256(b"unique evidence page").hexdigest()})
        returns = [page for message in seen[-1] for part in message.parts
                   if getattr(part, "part_kind", "") == "tool-return" and isinstance(part.content, list) for page in part.content]
        self.assertEqual(sum(page.get("content") == "unique evidence page" for page in returns), 1)
        self.assertEqual(sum(page.get("status") == "already_read" for page in returns), 2)
        self.assertEqual([row["read_indices"] for row in trace["model_requests"]], [[], [0], [0], [0]])

    def test_finalizer_keeps_first_page_once_and_actual_request_budget(self):
        data = payload()
        final_pages = []

        def respond(messages, info):
            for message in messages:
                for part in message.parts:
                    if getattr(part, "part_kind", "") == "user-prompt" and isinstance(part.content, str):
                        value = json.loads(part.content)
                        if "initial_materials" in value:
                            final_pages.extend(value["read_evidence"])
                            return ModelResponse(parts=[ToolCallPart("final_result", {
                                "answer": "Current evidence only", "suggested_actions": [],
                                "verification_steps": [], "citations": ["FILE-current"],
                            })])
            return ModelResponse(parts=[ToolCallPart("read_evidence", {"references": ["FILE-current"]})])

        with patch.object(runner, "OpenAIProvider"), patch.object(runner, "OpenAIChatModel", return_value=FunctionModel(respond)):
            result = asyncio.run(runner.analyze(data))
        trace = result["evidence_trace"]
        self.assertEqual(result["model_usage"]["requests"], 6)
        self.assertEqual(len(trace["read_attempts"]), 5)
        self.assertEqual(len(final_pages), 1)
        self.assertEqual(final_pages[0]["content"], "unique evidence page")
        self.assertEqual(trace["finalizer"]["read_indices"], [0])
        self.assertEqual([row["read_indices"] for row in trace["model_requests"]], [[], [0], [0], [0], [0], [0]])

    def test_actual_page_identity_reuses_different_requested_lengths_only_when_end_matches(self):
        data = payload(); read = tool(data)
        first = read(["FILE-current"], 0, 6000)[0]
        repeated = read(["FILE-current"], 0, 12000)[0]
        self.assertEqual(repeated["status"], "already_read")
        self.assertNotIn("content", repeated)
        self.assertEqual(first["next_offset"], repeated["next_offset"])
        other = read(["FILE-current"], 0, 3)[0]
        self.assertEqual(other["content"], "uni")
        self.assertEqual(len(data["evidence_trace"]["reads"]), 2)
        self.assertEqual(read(["FILE-current"], 3, 3)[0]["content"], "que")

    def test_duplicate_attempt_budget_does_not_fake_unique_reads_or_expand_unboundedly(self):
        data = payload(); read = tool(data)
        for _ in range(60):
            read(["FILE-current"], 0, 6000)
        blocked = read(["FILE-current"], 0, 6000)[0]
        self.assertIn("error", blocked)
        self.assertEqual(len(data["evidence_trace"]["read_attempts"]), 60)
        self.assertEqual(len(data["evidence_trace"]["reads"]), 1)

    def test_identical_body_in_other_authorized_source_is_a_new_page(self):
        data = payload()
        data["references"] = [{"reference": "KN-current", "title": "knowledge", "content": "unique evidence page"}]
        read = tool(data)
        first = read(["FILE-current"])[0]
        other = read(["KN-current"])[0]
        self.assertEqual(first["content"], other["content"])
        self.assertEqual(len(data["evidence_trace"]["reads"]), 2)
        self.assertEqual([row["first_read_index"] for row in data["evidence_trace"]["read_attempts"]], [0, 1])

    def test_foreign_and_invalid_ranges_are_still_denied_before_reuse(self):
        data = payload(); read = tool(data)
        read(["FILE-current"])
        self.assertIn("error", read(["FILE-foreign"])[0])
        self.assertIn("error", read(["FILE-current"], -1, 100)[0])
        self.assertEqual(len(data["evidence_trace"]["reads"]), 1)


if __name__ == "__main__":
    unittest.main()
