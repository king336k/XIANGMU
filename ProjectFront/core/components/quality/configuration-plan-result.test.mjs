import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../../../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
function load(file, mocks = {}) {
  const exports = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(file, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((name) => mocks[name] ?? require(name), exports);
  return exports;
}
const types = load("../remote-diagnostics/types.ts");
const reports = load("./report-summary.ts");
const { ConfigurationPlanResult } = load("./configuration-plan-result.tsx", {
  "../remote-diagnostics/types": types,
  "./report-summary": reports,
  "./agent-report-text": { AgentReportText: ({ content }) => React.createElement("p", null, content) },
});
function render(run) {
  return renderToStaticMarkup(React.createElement(ConfigurationPlanResult, { run, onHistory() {} }));
}
test("submitted repair exposes actual queue and verification stages without another request", () => {
  const queued = render({ id: "private-run", status: "queued", queue: { reason: "device_busy" } });
  assert.match(queued, /本次修复/);
  assert.match(queued, /等待采集电脑空闲/);
  assert.match(queued, /animate-spin/);
  assert.match(queued, /查看完整处理记录/);
  assert.doesNotMatch(queued, /private-run|<details[^>]*open/);
  const verifying = render({ id: "private-run", status: "running", queue: { stage: "verify" } });
  assert.match(verifying, /复测中|正在复测/);
  assert.doesNotMatch(verifying, /已修复/);
});
test("completed unmodified blocked plan names the reason and never claims recovery", () => {
  const html = render({
    id: "run",
    status: "completed",
    result: {
      actual_write: false,
      configuration_blocked_reason: "配置已变化，请重新诊断。",
      summary: "旧摘要",
      root_cause: "读取配置与计划快照不一致。",
    },
  });
  assert.match(html, /未修改/);
  assert.match(html, /配置已变化，请重新诊断/);
  assert.match(html, /详细证据与处理过程/);
  assert.doesNotMatch(html, /已修复|animate-spin|<details[^>]*open/);
});
test("configuration validation remains pending business verification and generic completion is unresolved", () => {
  const pending = render({
    id: "run",
    status: "completed",
    result: {
      configuration_verified: true,
      configuration_repaired: true,
      business_verified: false,
      verification_passed: true,
      actual_write: true,
    },
  });
  assert.match(pending, /待验证/);
  assert.doesNotMatch(pending, /已修复/);
  assert.match(render({ id: "run", status: "completed", result: { summary: "仍需现场核查。" } }), /未解决/);
  const repaired = render({ id: "run", status: "completed", result: { repaired: true, verification_passed: true } });
  assert.match(repaired, /已修复/);
});
