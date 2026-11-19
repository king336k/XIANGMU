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
    def test_four_part_answer_and_optional_details_roundtrip_without_rewriting_facts(self):
        answer="**问题**：上报时复位失败；本轮配置复查已通过，运动仍待验收。\n**原因**：已确认历史日志记录目标超限，当前修改回执对应配置恢复。\n**处理**：已按批准计划更正初值；本轮未执行运动。\n**验证**：配置语义检查通过；原复位业务需现场授权验证。"
        def respond(messages,info):
            value=report(['由现场人员在安全条件下执行原复位操作。'],['原复位完成且无同类错误才通过业务验收。'])
            value.update(answer=answer,evidence_details='实际配置位置及改动保存在现场执行回执；知识机制见 KN-reporting-v1。',citations=['DESCRIPTION','KN-reporting-v1'])
            return ModelResponse(parts=[ToolCallPart('final_result',value)])
        data=payload();data['references']=[{'reference':'KN-reporting-v1','title':'配置与业务验收边界','content':'配置通过不等于业务恢复'}]
        result=runner.create_agent(FunctionModel(respond),data).run_sync('分析本轮材料')
        self.assertEqual(result.output.answer,answer)
        self.assertIn('KN-reporting-v1',result.output.evidence_details)
        self.assertLess(len(result.output.answer),400)

    def test_details_cannot_hide_foreign_reference_or_bypass_its_length_bound(self):
        calls=[]
        def respond(messages,info):
            calls.append(1);value=report(['只读核对现场配置。'],['按原失败操作确认结果。'])
            value['evidence_details']='具体依据 KN-foreign-source'
            return ModelResponse(parts=[ToolCallPart('final_result',value)])
        with self.assertRaises(UnexpectedModelBehavior):runner.create_agent(FunctionModel(respond),payload()).run_sync('分析')
        self.assertEqual(len(calls),2)
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):runner.Report.model_validate({**report(), 'evidence_details':'x'*10001})

    def test_new_short_generation_contract_keeps_legacy_report_readable(self):
        from pydantic import ValidationError
        old={**report(['核查同事件证据。'],['按原操作复测。']), 'answer':'旧报告内容'*100,'evidence_details':'旧详细依据'*300}
        self.assertEqual(runner.Report.model_validate(old).answer,old['answer'])
        with self.assertRaises(ValidationError):runner.ActionableReport.model_validate(old)
        schema=runner.create_agent(None,payload()).output_type.model_json_schema()
        self.assertEqual(schema['properties']['answer']['maxLength'],220)
        self.assertEqual(schema['properties']['evidence_details']['maxLength'],800)

    def test_short_three_part_report_preserves_before_after_and_structured_source_ids(self):
        answer='**故障**：复位目标超限，原始日志直接说明失败环节。\n**已处理**：按批准计划将右臂初值3.3065改为0.3065，配置复查通过。\n**待验证**：由现场人员在安全条件下执行复位，确认成功且不再报同类错误。'
        source='FILE-11111111-2222-4333-8444-555555555555'
        def respond(messages,info):
            value=report(['由现场人员执行原复位操作。'],['复位完成且无同类错误，才通过业务验收。'])
            value.update(answer=answer,evidence_details='节点日志：reset goal is invalid: joint limit violation。',citations=[source])
            return ModelResponse(parts=[ToolCallPart('final_result',value)])
        data=payload();data['evidence']=[{'reference':source,'title':'复位节点原始日志','content':'reset goal is invalid: joint limit violation'}]
        result=runner.create_agent(FunctionModel(respond),data).run_sync('分析')
        self.assertEqual(result.output.answer,answer)
        self.assertEqual(result.output.citations,[source])
        self.assertLessEqual(len(result.output.answer),220)
        self.assertNotIn(source,result.output.answer+result.output.evidence_details)
        self.assertIn('3.3065改为0.3065',result.output.answer)

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
