"""Fixed non-echo corrections and actual fallback causes within unchanged budgets."""
import asyncio
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from pydantic import ValidationError
from pydantic_ai import ModelRetry
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

spec = importlib.util.spec_from_file_location("hint_runner", Path(__file__).with_name("runner.py"))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
PRIVATE = "PRIVATE_REF_QUOTE_MATERIAL_DO_NOT_ECHO"


def payload():
    return {"config": {"model": "offline", "base_url": "https://synthetic.invalid", "api_key": "synthetic"},
            "text": PRIVATE, "evidence": [{"reference": "FILE-current", "content": PRIVATE}],
            "references": [{"reference": "PLATFORM-RECEIPT", "content": PRIVATE}]}


def report(reference="FILE-current", severity="", evidence=None):
    return {"answer": "Current authorized facts", "suggested_actions": [], "verification_steps": [],
            "citations": [reference], "severity_assessment": {
                "severity": severity, "basis": "Current impact only", "evidence": evidence or []}}


def item(reference):
    return {"reference": reference, "quote": PRIVATE}


class Collector:
    def output_validator(self, function):
        self.validate = function
        return function


def validator():
    agent = Collector()
    runner.register_reference_validator(agent, payload())
    return agent.validate


def retry_text(messages):
    return " ".join(str(part.content) for message in messages for part in message.parts
                    if getattr(part, "part_kind", "") in {"retry-prompt", "tool-return"}
                    and getattr(part, "tool_name", "") == "final_result")


class ReferenceHintTests(unittest.TestCase):
    def test_five_original_predicates_have_fixed_safe_categories_and_hints(self):
        cases = [
            (report(PRIVATE), ["citation_not_in_current_allowlist"], "citations"),
            (report(), ["confidence_not_in_final_citations"], "confidence_references"),
            (report(evidence=[item("FILE-" + PRIVATE)]),
             ["severity_reference_not_allowed", "severity_reference_not_cited"], "本任务材料清单"),
            (report("PLATFORM-RECEIPT", evidence=[item("FILE-current")]),
             ["severity_reference_not_cited"], "最终 citations"),
            (report("PLATFORM-RECEIPT", evidence=[item("PLATFORM-RECEIPT")]),
             ["severity_reference_not_file"], "severity 留空且 evidence 设为空数组"),
        ]
        for index, (value, categories, hint) in enumerate(cases):
            with self.subTest(index=index):
                typed = runner.Report.model_validate(value)
                if index == 1:
                    # Report also checks this at schema time; preserve the validator predicate independently.
                    typed = typed.model_copy(update={"confidence_references": [PRIVATE]})
                with self.assertRaises(ModelRetry) as caught:
                    validator()(typed)
                self.assertEqual(list(caught.exception.reference_categories), categories)
                self.assertIn(hint, str(caught.exception))
                self.assertNotIn(PRIVATE, str(caught.exception))
                safe = runner.safe_failure(caught.exception)
                self.assertEqual(safe["validation_categories"], categories)
                self.assertNotIn(PRIVATE, json.dumps(safe))

    def test_empty_receipt_still_rejected_and_fixed_hint_allows_existing_single_correction(self):
        calls = []

        def respond(messages, info):
            calls.append(1)
            if len(calls) == 1:
                value = report("PLATFORM-RECEIPT", evidence=[item("PLATFORM-RECEIPT")])
            else:
                hint = retry_text(messages)
                self.assertIn("severity 留空且 evidence 设为空数组", hint)
                self.assertIn("PLATFORM", hint)
                self.assertNotIn(PRIVATE, hint)
                value = report("PLATFORM-RECEIPT")
            return ModelResponse(parts=[ToolCallPart("final_result", value)])

        with patch.object(runner, "OpenAIProvider"), patch.object(runner, "OpenAIChatModel", return_value=FunctionModel(respond)):
            result = asyncio.run(runner.analyze(payload()))
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["model_usage"]["requests"], 2)
        self.assertFalse(result["evidence_trace"]["finalizer"]["used"])
        self.assertEqual(result["severity_assessment"]["evidence"], [])

    def test_positive_severity_file_only_and_current_allowlist_and_citation_rules_remain(self):
        for severity in ["", "minor"]:
            with self.subTest(severity=severity), self.assertRaises(ModelRetry):
                validator()(runner.Report.model_validate(report("PLATFORM-RECEIPT", severity, [item("PLATFORM-RECEIPT")])))
        for severity in ["", "critical", "major", "minor", "trivial"]:
            typed = runner.Report.model_validate(report("FILE-current", severity, [item("FILE-current")]))
            self.assertIs(validator()(typed), typed)

    def test_reference_acceptance_matches_previous_contract_across_current_and_foreign_sources(self):
        references = ["DESCRIPTION", "FILE-current", "PLATFORM-RECEIPT", "FILE-foreign", PRIVATE]
        allowed = {"DESCRIPTION", "FILE-current", "PLATFORM-RECEIPT"}
        validate = validator()
        for cited in references:
            for evidence_ref in references:
                for severity in ["", "minor"]:
                    typed = runner.Report.model_validate(report(cited, severity, [item(evidence_ref)]))
                    # Frozen original acceptance contract, independent of hint/category implementation.
                    rejected = cited not in allowed or evidence_ref not in allowed or evidence_ref != cited or not evidence_ref.startswith("FILE-")
                    with self.subTest(cited=cited, evidence_ref=evidence_ref, severity=severity):
                        if rejected:
                            with self.assertRaises(ModelRetry):
                                validate(typed)
                        else:
                            self.assertIs(validate(typed), typed)

    def test_safe_failure_filters_unknown_category_attributes_without_inspecting_messages(self):
        error = ModelRetry(PRIVATE)
        error.reference_categories = ("severity_reference_not_file", PRIVATE, {}, "severity_reference_not_file")
        info = runner.safe_failure(error)
        self.assertEqual(info["validation_categories"], ["severity_reference_not_file"])
        self.assertNotIn(PRIVATE, json.dumps(info))


class FinalizerReasonTests(unittest.TestCase):
    def analyze(self, respond):
        with patch.object(runner, "OpenAIProvider"), patch.object(runner, "OpenAIChatModel", return_value=FunctionModel(respond)):
            return asyncio.run(runner.analyze(payload()))

    def test_actual_reference_retry_finalizer_retains_reason_and_categories_after_success(self):
        calls = []

        def respond(messages, info):
            calls.append(1)
            value = report("PLATFORM-RECEIPT", evidence=[item("PLATFORM-RECEIPT")]) if len(calls) < 3 else report()
            return ModelResponse(parts=[ToolCallPart("final_result", value)])

        result = self.analyze(respond)
        trace = result["evidence_trace"]
        self.assertEqual(trace["finalizer"]["reason"], "output_reference_invalid")
        self.assertEqual(trace["finalizer"]["validation_categories"], ["severity_reference_not_file"])
        self.assertEqual(len(calls), 3)
        self.assertEqual(result["model_usage"]["requests"], 3)
        self.assertNotIn(PRIVATE, json.dumps(trace))

    def test_actual_schema_exhaustion_reason_comes_from_class_chain(self):
        calls = []

        def respond(messages, info):
            calls.append(1)
            return ModelResponse(parts=[ToolCallPart("final_result", report() if len(calls) == 3 else {"answer": PRIVATE})])

        finalizer = self.analyze(respond)["evidence_trace"]["finalizer"]
        self.assertEqual(finalizer["reason"], "output_schema_invalid")
        self.assertEqual(finalizer["validation_categories"], [])
        self.assertEqual(len(calls), 3)

    def test_actual_usage_exhaustion_keeps_five_plus_one_request_budget(self):
        calls = []

        def respond(messages, info):
            calls.append(1)
            if len(calls) == 6:
                return ModelResponse(parts=[ToolCallPart("final_result", report())])
            return ModelResponse(parts=[ToolCallPart("read_evidence", {"references": ["DESCRIPTION"]})])

        result = self.analyze(respond)
        self.assertEqual(result["evidence_trace"]["finalizer"]["reason"], "usage_limit")
        self.assertEqual(result["model_usage"]["requests"], 6)

    def test_actual_timeout_reason_does_not_read_exception_text(self):
        calls = []

        def respond(messages, info):
            calls.append(1)
            if len(calls) == 1:
                raise TimeoutError("output_reference_invalid " + PRIVATE)
            return ModelResponse(parts=[ToolCallPart("final_result", report())])

        trace = self.analyze(respond)["evidence_trace"]
        self.assertEqual(trace["finalizer"]["reason"], "model_timeout")
        self.assertNotIn(PRIVATE, json.dumps(trace))

    def test_old_modelretry_without_categories_is_reference_reason_but_not_guessed_category(self):
        outer = UnexpectedModelBehavior(PRIVATE)
        outer.__cause__ = ModelRetry("severity_reference_not_file " + PRIVATE)
        self.assertEqual(runner.finalizer_failure(outer), {
            "reason": "output_reference_invalid", "validation_categories": []})
        self.assertEqual(runner.finalizer_failure(ValueError("usage_limit " + PRIVATE)), {
            "reason": "unknown", "validation_categories": []})

    def test_schema_error_cause_uses_actual_validationerror(self):
        try:
            runner.Report.model_validate({"answer": {PRIVATE: PRIVATE}})
        except ValidationError as cause:
            outer = UnexpectedModelBehavior(PRIVATE)
            outer.__cause__ = cause
            self.assertEqual(runner.finalizer_failure(outer)["reason"], "output_schema_invalid")


if __name__ == "__main__":
    unittest.main(verbosity=2)
