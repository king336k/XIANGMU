import { reportSummary } from "./report-summary-fixture.js";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

function render(result, expanded = true) {
  const exports = {};
  let stateIndex = 0;
  const code = ts.transpileModule(
    readFileSync(new URL("../core/components/quality/diagnostics-panel.tsx", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
  ).outputText;
  const job = { id: "current", status: "completed", result, created_at: "now" };
  new Function("require", "exports", code)((id) => {
    if (id === "react") return { ...React, useState: (initial) => [stateIndex++ === 4 ? expanded : initial, () => {}] };
    if (id === "swr")
      return {
        default: (url) => ({
          data: url.endsWith("/status/")
            ? { configured: true }
            : { results: [job], count: 1, current_report: job, latest_attempt: job },
          mutate() {},
        }),
      };
    if (id === "@plane/utils") return { renderNumericDateTime: () => "2026/11/14" };
    if (id === "@plane/ui") return { Button: (props) => React.createElement("button", props) };
    if (id === "@/components/knowledge/assistant-markdown")
      return { AssistantMarkdown: ({ content }) => React.createElement("p", null, content) };
    if (id === "./types") return { can: () => false, severityNames: {} };
    if (id === "./use-collection-pagination")
      return { useCollectionPagination: () => ({ query: "page=1", paging: {} }) };
    if (id === "./shared") return { Paging: () => null, Badge: () => null };
    if (id === "./deployment-snapshots") return { DeploymentSnapshots: () => null };
    if (id === "./report-summary") return reportSummary;
    if (id === "./api") return { qualityApi: {}, errorMessage: String };
    if (id === "lucide-react") return new Proxy({}, { get: () => () => null });
    return require(id);
  }, exports);
  return renderToStaticMarkup(
    React.createElement(exports.DiagnosticsPanel, { base: "/quality/", defectId: "d", context: {} })
  );
}

test("诊断成功后仍在现有进度展开区显示之前失败次数与真实阶段", () => {
  const html = render({
    model_status: "completed",
    attempt_failures: [
      {
        attempt: 1,
        code: "MODEL_TIMEOUT",
        duration_ms: 30000,
        source: "agent_transport",
        transport_phase: "connect",
        deadline_kind: "unknown",
      },
      {
        attempt: 2,
        code: "MODEL_TIMEOUT",
        duration_ms: 61000,
        source: "agent_transport",
        transport_phase: "read",
        deadline_kind: "unknown",
      },
    ],
  });
  for (const text of ["报告已生成", "此前尝试", "第1次", "连接超时", "第2次", "响应超时", "30.0 秒", "61.0 秒"])
    assert.ok(html.includes(text), text);
  assert.ok(!html.includes("故障已解决") && !html.includes("机器人已恢复"));
});

test("材料阶段、请求时限和未知原因区分且不输出原始错误值", () => {
  const raw = "PRIVATE_PROVIDER_URL_BODY_TOKEN";
  for (const [failure, label] of [
    [
      {
        source: "pre_model_materials",
        transport_phase: "unknown",
        deadline_kind: "pre_model_materials",
        provider_called: false,
      },
      "材料读取超时",
    ],
    [{ source: "agent_deadline", transport_phase: "unknown", deadline_kind: "request_timeout" }, "单次请求超时"],
    [
      { source: "subprocess_deadline", transport_phase: "unknown", deadline_kind: "subprocess_deadline" },
      "诊断进程超时",
    ],
    [{ source: raw, transport_phase: raw, deadline_kind: raw }, "原因未知"],
    [{ source: "__proto__", transport_phase: "constructor", deadline_kind: "toString" }, "原因未知"],
  ]) {
    const html = render({
      model_status: "timeout",
      model_failure: { ...failure, message: raw },
      attempt_failures: [{ attempt: 1, code: "MODEL_TIMEOUT", duration_ms: 20, ...failure, message: raw }],
    });
    assert.ok(html.includes(label), label);
    assert.ok(!html.includes(raw));
    if (failure.provider_called === false) assert.ok(html.includes("未调用模型接口"));
  }
});

test("失败记录最多四条，旧报告缺字段不补造失败，关闭进度时不展开", () => {
  const rows = Array.from({ length: 9 }, (_, i) => ({
    attempt: i + 1,
    code: "MODEL_TIMEOUT",
    duration_ms: 200,
    source: "agent_transport",
    transport_phase: "read",
    deadline_kind: "unknown",
  }));
  const html = render({ model_status: "completed", attempt_failures: rows });
  assert.equal((html.match(/第\d次/g) || []).length, 4);
  assert.ok(!html.includes("第5次"));
  const legacy = render({ model_status: "completed" });
  assert.ok(!legacy.includes("此前尝试") && !legacy.includes("原因未知"));
  const collapsed = render({ model_status: "completed", attempt_failures: rows }, false);
  assert.ok(!collapsed.includes("此前尝试"));
  assert.ok(collapsed.includes('aria-expanded="false"'));
});

test("diagnostic evidence and raw technical tracing remain independently folded beneath the concise result", () => {
  const id = "95f89e89-3d92-4f6c-a6aa-9b95fddfcd88";
  const html = render({
    answer: "**故障**：初始化失败。\n**已处理**：初值3.3改为0.3。\n**待验证**：实际遥操作。",
    evidence_details: "日志：joint limit violation\nrun_id=" + id,
  });
  assert.match(html, /<summary[^>]*>关键依据<\/summary>/);
  assert.match(html, /<summary[^>]*>技术追踪<\/summary>/);
  assert.match(html, /<summary[^>]*>原始报告<\/summary>/);
  const basis = html.slice(html.indexOf("关键依据"));
  assert.ok(basis.indexOf("joint limit violation") < basis.indexOf("技术追踪"));
  assert.ok(basis.indexOf(id) > basis.indexOf("技术追踪"));
  assert.doesNotMatch(basis.split("技术追踪")[0], /95f89e89/);
});
