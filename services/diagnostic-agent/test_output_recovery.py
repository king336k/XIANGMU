"""Offline typed output recovery keeps invalid reports out of finalizer evidence."""

import asyncio
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError
from pydantic_ai import ModelRetry
from pydantic_ai.exceptions import ModelConnectionError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

spec = importlib.util.spec_from_file_location(
    "output_recovery_runner", Path(__file__).with_name("runner.py")
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def payload():
    return {
        "config": {
            "model": "offline",
            "base_url": "https://synthetic.invalid",
            "api_key": "synthetic",
        },
        "text": "current authorized evidence",
        "evidence": [],
        "references": [],
    }


def valid():
    return {
        "answer": "Only current authorized facts",
        "suggested_actions": [],
        "verification_steps": [],
        "citations": ["DESCRIPTION"],
    }


class OutputRecoveryTests(unittest.TestCase):
    def analyze(self, respond, data=None):
        data = data or payload()
        with (
            patch.object(runner, "OpenAIProvider"),
            patch.object(
                runner, "OpenAIChatModel", return_value=FunctionModel(respond)
            ),
        ):
            return asyncio.run(runner.analyze(data))

    def test_schema_retry_exhaustion_gets_one_clean_validated_finalizer(self):
        seen = []
        marker = "INVALID_MODEL_OUTPUT_MUST_NOT_BECOME_FACT"

        def respond(messages, info):
            seen.append(messages)
            value = valid() if len(seen) == 3 else {"answer": marker}
            return ModelResponse(parts=[ToolCallPart("final_result", value)])

        data = payload()
        result = self.analyze(respond, data)
        self.assertEqual(len(seen), 3)
        self.assertTrue(result["evidence_trace"]["finalizer"]["used"])
        self.assertEqual(
            [row["finalizer"] for row in result["evidence_trace"]["model_requests"]],
            [False, False, True],
        )
        self.assertNotIn(marker, str(seen[-1]))
        self.assertEqual(result["citations"], ["DESCRIPTION"])

    def test_reference_retry_exhaustion_gets_valid_finalizer_without_filtering(self):
        calls = []

        def respond(messages, info):
            calls.append(1)
            value = valid()
            if len(calls) < 3:
                value["citations"] = ["KN-foreign"]
            return ModelResponse(parts=[ToolCallPart("final_result", value)])

        result = self.analyze(respond)
        self.assertEqual(len(calls), 3)
        self.assertTrue(result["evidence_trace"]["finalizer"]["used"])
        self.assertEqual(result["citations"], ["DESCRIPTION"])

    def test_invalid_finalizer_is_rejected_at_zero_retry(self):
        calls = []

        def respond(messages, info):
            calls.append(1)
            return ModelResponse(
                parts=[ToolCallPart("final_result", {"answer": "invalid"})]
            )

        with self.assertRaises(UnexpectedModelBehavior):
            self.analyze(respond)
        self.assertEqual(len(calls), 3)

    def test_unclassified_behavior_and_provider_errors_do_not_trigger_recovery(self):
        wrapped = UnexpectedModelBehavior("wrapped provider failure")
        validation = ModelRetry("fixed validation detail")
        validation.__cause__ = ModelConnectionError(
            model_name="offline", message="private"
        )
        wrapped.__cause__ = validation
        for error in [
            UnexpectedModelBehavior("arbitrary bad provider behavior"),
            ModelConnectionError(model_name="offline", message="private"),
            wrapped,
        ]:
            with self.subTest(kind=type(error).__name__):
                calls = []

                def respond(messages, info, calls=calls, error=error):
                    calls.append(1)
                    raise error

                with self.assertRaises(type(error)):
                    self.analyze(respond)
                self.assertEqual(len(calls), 1)

    def test_validation_metadata_contains_no_model_values_or_error_messages(self):
        try:
            runner.Report.model_validate({"answer": {"secret": "private-model-value"}})
        except ValidationError as error:
            info = runner.safe_failure(error)
        self.assertTrue(info["validation_errors"])
        self.assertEqual(info["validation_errors"][0]["type"], "string_type")
        self.assertNotIn("private-model-value", json.dumps(info))
        self.assertNotIn("secret", json.dumps(info))


if __name__ == "__main__":
    unittest.main()
