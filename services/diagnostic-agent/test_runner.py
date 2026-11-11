import importlib.util
from pathlib import Path
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import UsageLimits

spec = importlib.util.spec_from_file_location("diagnostic_runner", Path(__file__).with_name("runner.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
payload = {
    "text": "recording.log: connection refused",
    "evidence": [{"reference": "FILE-local", "title": "recording.log"}],
    "references": [{"reference": "KN-local-v1", "title": "通信检查", "content": "检查连接与驱动状态"}],
}
agent = module.create_agent(TestModel(custom_output_args={
    "answer": "日志出现连接失败，根因待验证。",
    "suggested_actions": ["检查驱动状态"],
    "verification_steps": ["重新连接后确认日志"],
    "citations": ["FILE-local"],
}), payload)
result = agent.run_sync("分析本次连接异常", usage_limits=UsageLimits(request_limit=4, tool_calls_limit=6))
assert result.output.citations == ["FILE-local"]
calls = [part.tool_name for message in result.all_messages() for part in message.parts if part.part_kind == "tool-call"]
assert "read_evidence" in calls and "search_case_knowledge" in calls
print({"typed_report": True, "controlled_tools_called": sorted(set(calls)), "external_model_called": False})

tool = agent._function_toolset.tools["read_evidence"].function
batch = tool(["FILE-local", "KN-local-v1", "FILE-not-authorized"])
assert batch[0]["reference"] == "FILE-local"
assert batch[1]["content"] == "检查连接与驱动状态"
assert batch[2]["error"] == "当前任务没有此材料"
print({"batch_evidence_valid": True, "foreign_reference_denied": True})
