"""Offline typed-agent reference correction within the existing retry budget."""

import asyncio
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import UsageLimits

spec = importlib.util.spec_from_file_location(
    "reference_runner", Path(__file__).with_name("runner.py")
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def payload():
    return {
        "config": {
            "model": "test",
            "base_url": "https://synthetic.invalid",
            "api_key": "synthetic",
        },
        "text": "当前测试材料",
        "evidence": [
            {
                "reference": "FILE-current",
                "title": "current.log",
                "content": "ERROR local failure",
            }
        ],
        "references": [
            {
                "reference": "KN-current-v1",
                "title": "可信知识",
                "content": "核对当前事件",
            }
        ],
    }


def report(ref):
    return {
        "answer": "当前材料支持局部异常，根因待核验。",
        "suggested_actions": [],
        "verification_steps": [],
        "citations": [ref],
    }


class ReferenceValidationTests(unittest.TestCase):
    def test_foreign_reference_is_corrected_once_by_real_typed_agent(self):
        seen = []
        forbidden = "FILE-secret-foreign-reference"

        def respond(messages, info):
            seen.append(messages)
            ref = forbidden if len(seen) == 1 else "FILE-current"
            return ModelResponse(parts=[ToolCallPart("final_result", report(ref))])

        agent = runner.create_agent(FunctionModel(respond), payload())
        result = agent.run_sync(
            "分析当前材料", usage_limits=UsageLimits(request_limit=2)
        )
        self.assertEqual(result.output.citations, ["FILE-current"])
        self.assertEqual(len(seen), 2)
        retries = [
            part.content
            for message in seen[-1]
            for part in message.parts
            if part.part_kind in {"retry-prompt", "tool-return"}
            and getattr(part, "tool_name", "") == "final_result"
        ]
        self.assertEqual(len(retries), 1)
        self.assertNotIn(forbidden, str(retries))
        self.assertNotIn("ERROR local failure", str(retries))
        self.assertIn("本任务材料清单中的编号", str(retries))

    def test_persistent_foreign_reference_exhausts_one_correction_without_filtering(
        self,
    ):
        calls = []

        def respond(messages, info):
            calls.append(1)
            return ModelResponse(
                parts=[ToolCallPart("final_result", report("KN-foreign"))]
            )

        agent = runner.create_agent(FunctionModel(respond), payload())
        with self.assertRaises(UnexpectedModelBehavior):
            agent.run_sync("分析", usage_limits=UsageLimits(request_limit=3))
        self.assertEqual(len(calls), 2)

    def test_description_and_current_knowledge_are_legal_without_a_correction(self):
        for reference in ["DESCRIPTION", "KN-current-v1", "FILE-current"]:
            calls = []

            def respond(messages, info, calls=calls, reference=reference):
                calls.append(1)
                return ModelResponse(
                    parts=[ToolCallPart("final_result", report(reference))]
                )

            result = runner.create_agent(FunctionModel(respond), payload()).run_sync(
                "分析"
            )
            self.assertEqual(result.output.citations, [reference])
            self.assertEqual(len(calls), 1)

    def test_severity_evidence_reference_uses_the_same_task_allowlist(self):
        calls = []

        def respond(messages, info):
            calls.append(messages)
            value = report("FILE-current")
            value["severity_assessment"] = {
                "severity": "minor",
                "basis": "本次局部影响",
                "evidence": [
                    {
                        "reference": "FILE-foreign"
                        if len(calls) == 1
                        else "FILE-current",
                        "quote": "ERROR local failure",
                    }
                ],
            }
            return ModelResponse(parts=[ToolCallPart("final_result", value)])

        result = runner.create_agent(FunctionModel(respond), payload()).run_sync("分析")
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            result.output.severity_assessment.evidence[0].reference, "FILE-current"
        )

    def test_finalizer_foreign_reference_is_rejected_without_another_request(self):
        data = payload()
        calls = []

        def respond(messages, info):
            calls.append(1)
            if len(calls) == 1:
                raise TimeoutError()
            return ModelResponse(
                parts=[ToolCallPart("final_result", report("KN-foreign"))]
            )

        with (
            patch.object(runner, "OpenAIProvider"),
            patch.object(
                runner, "OpenAIChatModel", return_value=FunctionModel(respond)
            ),
            self.assertRaises(UnexpectedModelBehavior),
        ):
            asyncio.run(runner.analyze(data))
        self.assertEqual(len(calls), 2)
        self.assertTrue(data["evidence_trace"]["finalizer"]["used"])

    def test_allowed_but_uncited_severity_reference_requires_correction(self):
        calls = []

        def respond(messages, info):
            calls.append(messages)
            value = report("DESCRIPTION" if len(calls) == 1 else "FILE-current")
            value["severity_assessment"] = {
                "severity": "minor",
                "basis": "局部影响",
                "evidence": [
                    {"reference": "FILE-current", "quote": "ERROR local failure"}
                ],
            }
            return ModelResponse(parts=[ToolCallPart("final_result", value)])

        result = runner.create_agent(FunctionModel(respond), payload()).run_sync("分析")
        self.assertEqual(len(calls), 2)
        self.assertEqual(result.output.citations, ["FILE-current"])

    def test_foreign_confidence_reference_cannot_bypass_final_citation_allowlist(self):
        calls = []

        def respond(messages, info):
            calls.append(messages)
            reference = "KN-foreign" if len(calls) == 1 else "KN-current-v1"
            value = report(reference)
            value.update(
                model_confidence=0.8,
                evidence_assessment="partial",
                confidence_basis="当前依据",
                confidence_references=[reference],
            )
            return ModelResponse(parts=[ToolCallPart("final_result", value)])

        result = runner.create_agent(FunctionModel(respond), payload()).run_sync("分析")
        self.assertEqual(len(calls), 2)
        self.assertEqual(result.output.confidence_references, ["KN-current-v1"])


if __name__ == "__main__":
    unittest.main()
