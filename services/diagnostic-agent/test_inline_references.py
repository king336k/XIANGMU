"""References embedded in report prose obey the same task boundary as citations."""
import importlib.util
import json
import unittest
from pathlib import Path

from pydantic_ai import ModelRetry
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

spec = importlib.util.spec_from_file_location('inline_runner', Path(__file__).with_name('runner.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
CURRENT = 'KN-c5c14e32-9039-4693-b5e5-80268a9d599b-v1'
FOREIGN = 'KN-c5c14e32-9039-469b-b5e5-80268a9d599b-v1'


class Collector:
    def output_validator(self, function):
        self.validate = function
        return function


def validate(value):
    agent = Collector()
    runner.register_reference_validator(agent, {'evidence': [{'reference': 'FILE-current'}],
                                               'references': [{'reference': CURRENT}]})
    return agent.validate(runner.Report.model_validate(value))


def report():
    return {'answer': '本次材料支持局部异常。', 'suggested_actions': [], 'verification_steps': [],
            'citations': ['FILE-current', CURRENT]}


class InlineReferenceTests(unittest.TestCase):
    def test_foreign_reference_in_any_prose_field_is_rejected_without_echo(self):
        for field in ['answer', 'suggested_actions', 'verification_steps', 'confidence_basis']:
            for wrapped in [FOREIGN, '[' + FOREIGN + ']', '_' + FOREIGN + '_', '__' + FOREIGN + '__', '-' + FOREIGN]:
                with self.subTest(field=field, wrapped=wrapped):
                    value = report()
                    text = '核对同一事件 [' + wrapped + ']'
                    value[field] = [text] if field.endswith(('actions', 'steps')) else text
                    with self.assertRaises(ModelRetry) as caught:
                        validate(value)
                    self.assertIn('inline_reference_not_allowed', caught.exception.reference_categories)
                    self.assertNotIn(FOREIGN, str(caught.exception))
                    self.assertNotIn(FOREIGN, json.dumps(runner.safe_failure(caught.exception)))

    def test_current_inline_reference_also_must_be_cited(self):
        value = report()
        value['citations'] = ['FILE-current']
        value['verification_steps'] = ['核对 [' + CURRENT + ']']
        with self.assertRaises(ModelRetry) as caught:
            validate(value)
        self.assertIn('inline_reference_not_cited', caught.exception.reference_categories)

    def test_exact_current_references_and_ordinary_filenames_remain_unchanged(self):
        value = report()
        value['verification_steps'] = ['核对 [' + CURRENT + ']，读取 recording.log；FILE 是文件标记。']
        self.assertEqual(validate(value).model_dump()['verification_steps'], value['verification_steps'])

    def test_same_boundary_applies_to_finalizer_registration(self):
        # Both main and finalizer use the same registration function.
        value = report()
        value['suggested_actions'] = ['参照 [KN-foreign-v2]']
        with self.assertRaises(ModelRetry):
            validate(value)

    def test_real_typed_agent_uses_one_correction_without_silently_stripping_prose(self):
        calls = []

        def respond(messages, info):
            calls.append(messages)
            value = report()
            value['verification_steps'] = ['核对 [' + (FOREIGN if len(calls) == 1 else CURRENT) + ']']
            return ModelResponse(parts=[ToolCallPart('final_result', value)])

        payload = {'text': 'current material', 'evidence': [{'reference': 'FILE-current', 'content': 'current'}],
                   'references': [{'reference': CURRENT, 'content': 'approved knowledge'}]}
        result = runner.create_agent(FunctionModel(respond), payload).run_sync('分析当前材料')
        self.assertEqual(len(calls), 2)
        self.assertEqual(result.output.verification_steps, ['核对 [' + CURRENT + ']'])
        retry = [p.content for message in calls[-1] for p in message.parts
                 if getattr(p, 'part_kind', '') == 'retry-prompt']
        self.assertNotIn(FOREIGN, str(retry))

    def test_persistent_bad_inline_reference_exhausts_original_single_correction(self):
        calls = []

        def respond(messages, info):
            calls.append(1)
            value = report()
            value['answer'] = '核对 [' + FOREIGN + ']'
            return ModelResponse(parts=[ToolCallPart('final_result', value)])

        payload = {'text': 'current material', 'evidence': [{'reference': 'FILE-current', 'content': 'current'}],
                   'references': [{'reference': CURRENT, 'content': 'approved knowledge'}]}
        with self.assertRaises(UnexpectedModelBehavior):
            runner.create_agent(FunctionModel(respond), payload).run_sync('分析当前材料')
        self.assertEqual(len(calls), 2)

    def test_all_fixed_categories_survive_safe_failure_without_echoing_values(self):
        error = ModelRetry('private details')
        error.reference_categories = tuple(runner.REFERENCE_HINTS)
        info = runner.safe_failure(error)
        self.assertEqual(set(info['validation_categories']), set(runner.REFERENCE_HINTS))
        self.assertEqual(set(info['error_chain'][0]['reference_categories']), set(runner.REFERENCE_HINTS))
        self.assertNotIn('private details', json.dumps(info))


if __name__ == '__main__':
    unittest.main()
