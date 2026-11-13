"""Offline usage accounting, including the bounded finalizer after a timeout."""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("diagnostic_runner", Path(__file__).with_name("runner.py"))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class UsageTests(unittest.TestCase):
    def test_explicit_client_does_not_inherit_five_second_connection_cap(self):
        class FakeClient:
            async def __aenter__(self):return self
            async def __aexit__(self,*args):return None
        from unittest.mock import AsyncMock
        payload={"config":{"model":"test","base_url":"http://local.invalid","api_key":"synthetic","diagnostic_timeout_seconds":300}}
        with patch.object(runner,"AsyncOpenAI",return_value=FakeClient()), patch.object(runner,"DefaultAsyncHttpxClient") as http, patch.object(runner,"_analyze",new_callable=AsyncMock,return_value={"ok":True}):
            result=asyncio.run(runner.analyze(payload))
        self.assertEqual(result,{"ok":True})
        self.assertEqual(http.call_args.kwargs["timeout"],240)

    def test_finalizer_includes_usage_consumed_before_timeout(self):
        class FakeAgent:
            def __init__(self, fail=False):
                self.fail = fail
                self.output_validators = []

            def output_validator(self, function):
                self.output_validators.append(function)
                return function

            async def run(self, prompt, **kwargs):
                usage = kwargs.get("usage")
                if usage is not None and usage.requests >= kwargs["usage_limits"].request_limit:
                    raise runner.UsageLimitExceeded("request limit exceeded before finalizer")
                if usage is not None:
                    usage.requests += 2 if self.fail else 1
                    usage.input_tokens += 100 if self.fail else 30
                    usage.output_tokens += 20 if self.fail else 10
                if self.fail:
                    raise TimeoutError()
                return SimpleNamespace(output=runner.Report(answer="材料不足", suggested_actions=[], verification_steps=[], citations=["DESCRIPTION"]))

        payload = {"config": {"model": "test", "base_url": "http://local.invalid", "api_key": "synthetic"},
                   "text": "材料", "evidence": [], "references": []}
        with patch.object(runner, "OpenAIProvider"), patch.object(runner, "OpenAIChatModel"), \
             patch.object(runner, "create_agent", return_value=FakeAgent(True)), patch.object(runner, "Agent", return_value=FakeAgent()):
            result = asyncio.run(runner.analyze(payload))
        self.assertEqual(result["model_usage"], {"requests": 3, "input_tokens": 130, "output_tokens": 30})


if __name__ == "__main__":
    unittest.main()
