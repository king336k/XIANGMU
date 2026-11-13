"""Offline failure phases do not create an immediate second connection attempt."""

import asyncio
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

from openai._base_client import httpx2
from pydantic_ai.exceptions import ModelTimeoutError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

spec = importlib.util.spec_from_file_location(
    "finalizer_transport_runner", Path(__file__).with_name("runner.py")
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def payload():
    return {
        "config": {
            "model": "offline",
            "api_key": "synthetic",
            "base_url": "https://synthetic.invalid",
        },
        "text": "synthetic",
        "evidence": [],
        "references": [],
    }


def completed():
    return ModelResponse(
        parts=[
            ToolCallPart(
                "final_result",
                {
                    "answer": "材料不足，根因待验证。",
                    "suggested_actions": [],
                    "verification_steps": [],
                    "citations": ["DESCRIPTION"],
                },
            )
        ]
    )


class FinalizerTransportTests(unittest.TestCase):
    def analyze(self, error):
        data = payload()
        calls = []

        def respond(messages, info):
            calls.append(1)
            if len(calls) == 1:
                raise error
            return completed()

        with (
            patch.object(runner, "OpenAIProvider"),
            patch.object(
                runner, "OpenAIChatModel", return_value=FunctionModel(respond)
            ),
        ):
            try:
                result = asyncio.run(runner.analyze(data))
            except (ModelTimeoutError, TimeoutError) as caught:
                return data, calls, caught
        return data, calls, result

    def test_explicit_nonread_transport_phases_do_not_invoke_finalizer(self):
        for phase in ["connect", "write", "pool"]:
            with self.subTest(phase=phase):
                error = ModelTimeoutError(
                    model_name="offline", message="private details", phase=phase
                )
                data, calls, result = self.analyze(error)
                self.assertIs(result, error)
                self.assertEqual(len(calls), 1)
                self.assertFalse(data["evidence_trace"]["finalizer"]["used"])
                self.assertEqual(
                    [row["status"] for row in data["evidence_trace"]["model_requests"]],
                    ["failed"],
                )

    def test_actual_http_transport_timeout_causes_are_recognized_through_wrapper(self):
        for kind in [httpx2.ConnectTimeout, httpx2.WriteTimeout, httpx2.PoolTimeout]:
            with self.subTest(kind=kind.__name__):
                error = ModelTimeoutError(
                    model_name="offline", message="private details"
                )
                error.__cause__ = kind("private transport detail")
                data, calls, result = self.analyze(error)
                self.assertIs(result, error)
                self.assertEqual(len(calls), 1)
                self.assertFalse(data["evidence_trace"]["finalizer"]["used"])

    def test_read_timeout_and_unclassified_total_timeout_still_have_bounded_finalizer(
        self,
    ):
        for error in [
            ModelTimeoutError(model_name="offline", message="private", phase="read"),
            TimeoutError("private"),
        ]:
            with self.subTest(kind=type(error).__name__):
                data, calls, result = self.analyze(error)
                self.assertIsInstance(result, dict)
                self.assertEqual(len(calls), 2)
                self.assertTrue(data["evidence_trace"]["finalizer"]["used"])
                self.assertEqual(result["citations"], ["DESCRIPTION"])

    def test_error_text_does_not_classify_a_transport_phase(self):
        data, calls, result = self.analyze(TimeoutError("connect write pool"))
        self.assertIsInstance(result, dict)
        self.assertEqual(len(calls), 2)
        self.assertTrue(data["evidence_trace"]["finalizer"]["used"])


if __name__ == "__main__":
    unittest.main()
