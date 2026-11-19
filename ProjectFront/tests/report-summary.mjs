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
test("three point source summary stays concise and technical evidence is separated without changing original", () => {
  const main =
    "**故障**：初始化失败，根因待确认。\n**已处理**：初值由3.3065改为0.3065。\n**待验证**：完成一次实际遥操作。";
  assert.equal(reportSummary.compactReportText(main), main.replaceAll("**", ""));
  assert.deepEqual(
    reportSummary.reportSections("Agent 远程处理：已修复\n" + main).map((x) => x.label),
    ["故障", "已处理", "待验证"]
  );
  const raw =
    "日志：joint limit violation\n历史处理 run_id=95f89e89-3d92-4f6c-a6aa-9b95fddfcd88\nsha256: " +
    "a".repeat(64) +
    '\n{\n"repaired":true\n}';
  const evidence = reportSummary.reportEvidence(raw);
  assert.equal(evidence.readable, "日志：joint limit violation");
  assert.equal(evidence.original, raw);
  assert.equal(evidence.hasTechnical, true);
});
