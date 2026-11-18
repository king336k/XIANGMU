import { reportSummary } from "./report-summary-fixture.js";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
function render(findings) {
  const exports = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/quality/diagnostics-panel.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
    ).outputText
  )((id) => {
    if (id === "react") return { ...React, useState: (value) => [value, () => {}] };
    if (id === "swr")
      return {
        default: (url) => ({
          data: url.endsWith("/status/")
            ? { configured: true }
            : {
                results: [{ id: "j", status: "completed", created_at: "now", result: { method: "rules", findings } }],
                count: 1,
              },
          mutate() {},
        }),
      };
    if (id === "@plane/utils") return { renderNumericDateTime: () => "2026/11/09" };
    if (id === "@plane/ui") return { Button: (props) => React.createElement("button", props) };
    if (id === "./types") return { can: () => false };
    if (id === "./use-collection-pagination")
      return { useCollectionPagination: () => ({ query: "page=1", paging: {} }) };
    if (id === "./shared") return { Paging: () => null };
    if (id === "./deployment-snapshots") return { DeploymentSnapshots: () => null };
    if (id === "./report-summary") return reportSummary;
    if (id === "./api") return { qualityApi: {}, errorMessage: String };
    if (id === "lucide-react") return new Proxy({}, { get: () => () => null });
    if (id.startsWith("@/components/knowledge/"))
      return { AssistantMarkdown: ({ content }) => React.createElement("p", null, content) };
    return require(id);
  }, exports);
  return renderToStaticMarkup(
    React.createElement(exports.DiagnosticsPanel, { base: "/quality/", defectId: "d", context: {} })
  );
}
const finding = { kind: "rule-1", title: "网络异常", samples: ["连接失败"], basis: "来源摘要，需核实" };
test("规则发现显示原规则分值与来源，不称正确率", () => {
  const html = render([{ ...finding, confidence: 0.9, confidence_source: "rule" }]);
  assert.match(html, /规则分值90%/);
  assert.match(html, /规则参数/);
  assert.doesNotMatch(html, /正确率|准确率/);
});
test("旧报告或无效分值不显示虚假零，真实零分值可显示", () => {
  for (const extra of [
    {},
    { confidence: null },
    { confidence: NaN },
    { confidence: 2 },
    { confidence: "0.9" },
    { confidence: 0.9, confidence_source: "model" },
  ]) {
    assert.doesNotMatch(render([{ ...finding, ...extra }]), /规则分值/);
  }
  assert.match(render([{ ...finding, confidence: 0, confidence_source: "rule" }]), /规则分值0%/);
});
