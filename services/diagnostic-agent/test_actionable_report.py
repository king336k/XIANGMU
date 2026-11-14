"""Production report contract requires usable next steps without inventing fault facts."""

import asyncio
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

spec = importlib.util.spec_from_file_location(
    "actionable_runner", Path(__file__).with_name("runner.py")
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def payload(required=True):
    return {
        "config": {
            "model": "offline",
            "base_url": "https://synthetic.invalid",
            "api_key": "synthetic",
        },
        "text": "同窗频率通过，稳定性阻断；具体根因缺证据。",
        "evidence": [],
        "references": [],
        "require_actionable_report": required,
    }


def report(actions=None, verification=None):
    return {
        "answer": "平均频率达标不能替代稳定性验收，具体原因未定位。",
        "suggested_actions": actions or [],
        "verification_steps": verification or [],
        "citations": ["DESCRIPTION"],
    }


class ActionableReportTests(unittest.TestCase):
    def test_schema_exposes_minimum_nonblank_steps_for_production(self):
        schema = runner.create_agent(None, payload()).output_type.model_json_schema()
        for key in ["suggested_actions", "verification_steps"]:
            self.assertEqual(schema["properties"][key].get("minItems"), 1)
            self.assertEqual(schema["properties"][key]["items"].get("minLength"), 1)

    def test_actual_typed_agent_rejects_empty_steps_then_corrects_once(self):
        calls = []

        def respond(messages, info):
            calls.append(messages)
            value = (
                report()
                if len(calls) == 1
                else report(
                    ["只读对齐同窗源发送与接收计数、采样时间和资源趋势。"],
                    [
                        "同一完整观察窗按当前门限确认频率、最大间隔和最近消息年龄分别通过。"
                    ],
                )
            )
            return ModelResponse(parts=[ToolCallPart("final_result", value)])

        result = runner.create_agent(FunctionModel(respond), payload()).run_sync(
            "分析当前材料"
        )
        self.assertEqual(len(calls), 2)
        self.assertTrue(result.output.suggested_actions)
        self.assertTrue(result.output.verification_steps)

    def test_blank_entries_are_not_a_workaround_for_usable_steps(self):
        for steps in [[""], ["   "], ["\n\t"]]:
            with self.subTest(steps=steps):
                calls = []

                def respond(messages, info):
                    calls.append(1)
                    return ModelResponse(
                        parts=[ToolCallPart("final_result", report(steps, steps))]
                    )

                with self.assertRaises(UnexpectedModelBehavior):
                    runner.create_agent(FunctionModel(respond), payload()).run_sync(
                        "分析当前材料"
                    )
                self.assertEqual(len(calls), 2)

    def test_insufficient_evidence_allows_readonly_evidence_request_without_fake_repair(
        self,
    ):
        def respond(messages, info):
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "final_result",
                        report(
                            [
                                "当前原因未定位；仅补同一事件的最早错误和有效配置来源，勿执行控制操作。"
                            ],
                            [
                                "拿到该事件证据后分别核验根因假设；资料不足时保持未验证。"
                            ],
                        ),
                    )
                ]
            )

        result = runner.create_agent(FunctionModel(respond), payload()).run_sync("分析")
        self.assertIn("未定位", result.output.suggested_actions[0])

    def test_unversioned_legacy_agent_call_still_loads_without_imposing_new_contract(
        self,
    ):
        def respond(messages, info):
            return ModelResponse(parts=[ToolCallPart("final_result", report())])

        result = runner.create_agent(FunctionModel(respond), payload(False)).run_sync(
            "分析"
        )
        self.assertEqual(result.output.verification_steps, [])

    def test_finalizer_cannot_publish_empty_steps_when_main_output_is_incomplete(self):
        calls = []

        def respond(messages, info):
            calls.append(1)
            return ModelResponse(parts=[ToolCallPart("final_result", report())])

        with (
            patch.object(runner, "OpenAIProvider"),
            patch.object(
                runner, "OpenAIChatModel", return_value=FunctionModel(respond)
            ),
        ):
            with self.assertRaises(UnexpectedModelBehavior):
                asyncio.run(runner.analyze(payload()))
        self.assertEqual(
            len(calls), 3
        )  # Original main correction plus single finalizer; no budget increase.


if __name__ == "__main__":
    unittest.main(verbosity=2)
