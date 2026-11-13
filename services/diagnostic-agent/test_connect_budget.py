"""Connection establishment has its own bound without shortening model response time."""

import asyncio
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "connect_budget_runner", Path(__file__).with_name("runner.py")
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class ConnectBudgetTests(unittest.TestCase):
    def check_timeout(self, env, total, expected):
        observed = {}

        async def inspect(payload, client, budget):
            timeout = client._client.timeout
            observed.update(
                connect=timeout.connect,
                read=timeout.read,
                write=timeout.write,
                pool=timeout.pool,
                retries=client.max_retries,
            )
            return {"ok": True}

        with (
            patch.dict(runner.os.environ, env, clear=True),
            patch.object(runner, "_analyze", inspect),
        ):
            result = asyncio.run(
                runner.analyze(
                    {
                        "config": {
                            "base_url": "https://example.invalid/v1",
                            "api_key": "fixture",
                            "diagnostic_timeout_seconds": total,
                        }
                    }
                )
            )
        self.assertTrue(result["ok"])
        self.assertEqual(observed["connect"], expected)
        request_budget = total - min(60, total // 3)
        self.assertEqual(observed["read"], request_budget)
        self.assertEqual(observed["write"], request_budget)
        self.assertEqual(observed["pool"], request_budget)
        self.assertEqual(observed["retries"], 0)

    def test_default_connect_bound_preserves_response_budget(self):
        self.check_timeout({}, 300, 30)

    def test_configured_connect_bound_is_clamped_and_invalid_falls_back(self):
        for value, expected in [("8", 8), ("1", 5), ("600", 60), ("invalid", 30)]:
            with self.subTest(value=value):
                self.check_timeout(
                    {"DIAGNOSTIC_CONNECT_TIMEOUT_SECONDS": value}, 300, expected
                )

    def test_short_total_bounds_long_connect_setting(self):
        self.check_timeout({"DIAGNOSTIC_CONNECT_TIMEOUT_SECONDS": "60"}, 60, 40)


class AppliedPhaseTimeoutTests(unittest.TestCase):
    def test_actual_sdk_requests_keep_connect_bound_in_primary_and_finalizer(self):
        import json

        from openai._base_client import httpx2

        calls = []

        async def send(request):
            calls.append(dict(request.extensions["timeout"]))
            if len(calls) == 1:
                raise (
                    runner.TimeoutError("controlled")
                    if hasattr(runner, "TimeoutError")
                    else TimeoutError("controlled")
                )
            content = {
                "answer": "有限材料仅供条件式排查。",
                "suggested_actions": [],
                "verification_steps": [],
                "citations": ["DESCRIPTION"],
            }
            return httpx2.Response(
                200,
                request=request,
                json={
                    "id": "fixture",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "test",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": json.dumps(content),
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                },
            )

        http = runner.DefaultAsyncHttpxClient(
            timeout=240, transport=httpx2.MockTransport(send)
        )
        http.timeout.connect = 30

        async def execute():
            async with runner.AsyncOpenAI(
                api_key="fixture",
                base_url="https://example.invalid/v1",
                http_client=http,
                max_retries=0,
            ) as client:
                with patch.dict(
                    runner.os.environ, {"DIAGNOSTIC_CONNECT_TIMEOUT_SECONDS": "30"}
                ):
                    return await runner._analyze(
                        {
                            "config": {"model": "test"},
                            "text": "材料",
                            "evidence": [],
                            "references": [],
                        },
                        client,
                        300,
                    )

        asyncio.run(execute())
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["connect"], 30)
        self.assertEqual(calls[0]["read"], 240)
        self.assertEqual(calls[1]["connect"], 30)
        self.assertEqual(calls[1]["read"], 60)
