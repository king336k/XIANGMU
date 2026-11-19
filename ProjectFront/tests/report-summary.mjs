import assert from "node:assert/strict";
import test from "node:test";
import { reportSummary } from "./report-summary-fixture.js";
test("professional report preserves four factual points including unexecuted handling and unverified result", () => {
  const answer =
    "**问题**：遥操作初始化失败。\n**原因**：关节初值超限。\n**处理**：尚未执行修改。\n**验证**：尚未确认，需现场复测。\n详细证据与处理过程：\nPRIVATE_RAW_LOG";
  assert.equal(
    reportSummary.compactReportText(answer),
    "问题：遥操作初始化失败。\n原因：关节初值超限。\n处理：尚未执行修改。\n验证：尚未确认，需现场复测。"
  );
  assert.deepEqual(
    reportSummary.reportSections("Agent 远程处理：未自动修复\n" + answer).map((x) => x.label),
    ["问题", "原因", "处理", "验证"]
  );
});
