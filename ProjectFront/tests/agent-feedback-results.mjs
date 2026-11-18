import { reportSummary } from "./report-summary-fixture.js";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
function render(data, error, expanded = null) {
  const exports = {};
  const source = readFileSync(
    new URL("../core/components/quality/agent-feedback-results.tsx", import.meta.url),
    "utf8"
  );
  new Function(
    "require",
    "exports",
    ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } })
      .outputText
  )((name) => {
    if (name === "react") return { ...React, useState: () => [expanded, () => {}] };
    if (name === "./agent-feedback-actions") return { AgentFeedbackActions: () => null };
    if (name === "swr") return { default: () => ({ data, error, mutate() {} }) };
    if (name === "./report-summary") return reportSummary;
    if (name === "./api") return { qualityApi: {}, errorMessage: () => "读取失败" };
    if (name === "@plane/utils") return { renderNumericDateTime: (x) => x };
    return require(name);
  }, exports);
  return renderToStaticMarkup(
    React.createElement(exports.AgentFeedbackResults, { base: "/quality/", defectId: "same-defect", active: true })
  );
}
test("原缺陷诊断直接展示公开 Agent 回写，内部备注不作为现场结果", () => {
  const records = [
    { id: "internal", visibility: "internal", content: "Agent 远程处理：内部记录", created_at: "2026-11-19" },
    { id: "old", visibility: "public", content: "Agent 远程处理：已修复\n结论：旧结果", created_at: "2026-11-17" },
    {
      id: "new",
      visibility: "public",
      content: "Agent 远程处理：未自动修复\n结论：需要现场检查\n原因与证据：硬件标志阻止修复\n后续方案：检查接线",
      created_at: "2026-11-18",
    },
  ];
  const html = render(records);
  assert.match(html, /Agent 现场处理/);
  assert.match(html, /需要现场检查/);
  assert.match(html, /硬件标志阻止修复/);
  assert.match(html, /检查接线/);
  assert.doesNotMatch(html, /旧结果/);
  const old = render(records, undefined, { key: "same-defect:new", id: "old" });
  assert.match(old, /旧结果/);
  assert.doesNotMatch(old, /需要现场检查/);
  assert.ok(!html.includes("内部记录"));
});
test("没有结果和请求失败不宣称已修复", () => {
  assert.match(render([]), /暂无 Agent 现场处理结果/);
  assert.match(render(undefined, new Error()), /读取失败/);
});

test("只读验证通过以绿色状态呈现，未修复的普通完成不被推断为验证通过", () => {
  const verified = render([
    {
      id: "verified",
      visibility: "public",
      content: "Agent 远程处理：验证通过\n结论：现场检查正常",
      created_at: "2026-11-18",
    },
  ]);
  assert.match(verified, /text-success-primary[^>]*>验证通过/);
  assert.doesNotMatch(verified, /text-warning-primary/);
  const unresolved = render([
    {
      id: "unresolved",
      visibility: "public",
      content: "Agent 远程处理：未自动修复\n结论：证据不足",
      created_at: "2026-11-18",
    },
  ]);
  assert.match(unresolved, /text-warning-primary/);
  assert.doesNotMatch(unresolved, /验证通过/);
});
test("原诊断默认折叠，现场处理排在报告下方，操作记录明确标识 Agent", () => {
  const read = (name) => readFileSync(new URL("../core/components/quality/" + name, import.meta.url), "utf8");
  assert.ok(!read("diagnostics-panel.tsx").includes("open={current}"));
  assert.match(read("deployment-snapshots.tsx"), /open=\{!compact\}/);
  const detail = read("defect-detail.tsx");
  assert.ok(detail.indexOf("<DiagnosticsPanel") < detail.indexOf("<AgentFeedbackResults"));
  assert.match(read("collaboration-panel.tsx"), /Agent 现场处理结果/);
});

test("简短结论选完整原句并保留未知与模拟限定，原始过程完整折叠保留", () => {
  const content =
    "Agent 远程处理：验证通过\n结论：195与177模拟采集链路正常，未复现503。本轮未改配置。\n原因与证据：尚未完成实机验证，硬件原因待现场确认。\n已执行操作：读取现场状态。ROSA 检查 /var/log/robot/trace.json --verbose。\n复测：固定检查通过。\n后续方案：无需重启，继续观察。";
  const html = render([{ id: "latest", visibility: "public", content, created_at: "2026-11-18" }]);
  assert.match(html, /195与177模拟采集链路正常，未复现503。/);
  assert.match(html, /尚未完成实机验证，硬件原因待现场确认。/);
  assert.match(html, /<details[^>]*><summary[^>]*>详细证据与处理过程/);
  assert.doesNotMatch(html, /<details[^>]*open=/);
  assert.match(html, /ROSA 检查 \/var\/log\/robot\/trace.json --verbose/);
  assert.ok(html.indexOf("ROSA 检查") > html.indexOf("详细证据与处理过程"));
  assert.equal((html.match(/aria-expanded="true"/g) || []).length, 1);
});
