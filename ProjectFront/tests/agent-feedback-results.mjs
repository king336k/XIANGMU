import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
function render(data, error) {
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
    if (name === "./agent-feedback-actions") return { AgentFeedbackActions: () => null };
    if (name === "swr") return { default: () => ({ data, error, mutate() {} }) };
    if (name === "./api") return { qualityApi: {}, errorMessage: () => "读取失败" };
    if (name === "@plane/utils") return { renderNumericDateTime: (x) => x };
    return require(name);
  }, exports);
  return renderToStaticMarkup(
    React.createElement(exports.AgentFeedbackResults, { base: "/quality/", defectId: "same-defect", active: true })
  );
}
test("原缺陷诊断直接展示公开 Agent 回写，内部备注不作为现场结果", () => {
  const html = render([
    { id: "internal", visibility: "internal", content: "Agent 远程处理：内部记录", created_at: "2026-11-19" },
    { id: "old", visibility: "public", content: "Agent 远程处理：已修复\n结论：旧结果", created_at: "2026-11-17" },
    {
      id: "new",
      visibility: "public",
      content: "Agent 远程处理：未自动修复\n结论：需要现场检查\n原因与证据：硬件标志阻止修复\n后续方案：检查接线",
      created_at: "2026-11-18",
    },
  ]);
  assert.match(html, /Agent 现场处理/);
  assert.match(html, /需要现场检查/);
  assert.match(html, /硬件标志阻止修复/);
  assert.match(html, /检查接线/);
  assert.ok(html.indexOf("需要现场检查") < html.indexOf("旧结果"));
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
