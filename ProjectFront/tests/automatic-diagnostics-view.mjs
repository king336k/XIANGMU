import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
function render(rows) {
  const api = {};
  const code = ts.transpileModule(
    readFileSync(new URL("../core/components/quality/diagnostics-panel.tsx", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
  ).outputText;
  new Function("require", "exports", code)((id) => {
    if (id === "react") return { ...React, useState: (value) => [value, () => {}] };
    if (id === "swr")
      return {
        default: (url) => ({
          data: url.endsWith("/status/") ? { configured: true } : { results: rows, count: rows.length },
          mutate() {},
        }),
      };
    if (id === "@plane/utils") return { renderNumericDateTime: () => "2026/11/09" };
    if (id === "@plane/ui") return { Button: (props) => React.createElement("button", props) };
    if (id === "@/components/knowledge/assistant-markdown")
      return { AssistantMarkdown: ({ content }) => React.createElement("p", null, content) };
    if (id === "./types") return { can: () => false, severityNames: { "": "待评估", major: "严重", minor: "一般" } };
    if (id === "./use-collection-pagination")
      return { useCollectionPagination: () => ({ query: "page=1", paging: {} }) };
    if (id === "./shared")
      return { Paging: () => null, Badge: ({ label }) => React.createElement("span", null, label) };
    if (id === "./deployment-snapshots") return { DeploymentSnapshots: () => null };
    if (id === "./api") return { qualityApi: {}, errorMessage: String };
    if (id === "lucide-react") return new Proxy({}, { get: () => () => null });
    return require(id);
  }, api);
  return renderToStaticMarkup(
    React.createElement(api.DiagnosticsPanel, { base: "/quality/", defectId: "d", context: {} })
  );
}
test("材料引用同时显示原始上传包名和包内日志路径", () => {
  const html = render([
    {
      id: "named",
      status: "completed",
      mode: "rules",
      result: {
        method: "rules",
        model_status: "not_requested",
        sources: [
          {
            file_id: "file",
            name: "现场材料.zip",
            archive_entry: "logs/采集节点.log",
            read_bytes: 10,
            truncated: false,
          },
        ],
        citations: [{ reference: "FILE-file:logs/采集节点.log", title: "现场材料.zip / logs/采集节点.log" }],
        assignment: {
          module: { key: "daq", name: "DAQ" },
          assignee: "daq_owner",
          origin: "diagnostic",
          reason: "引用：采集原始.log。",
        },
      },
    },
  ]);
  assert.ok(html.includes("现场材料.zip / logs/采集节点.log"), html);
  assert.ok(html.includes("引用：采集原始.log。"), html);
  assert.ok(!html.includes("FILE-file"), html);
});
test("最新报告直接展开，超时保留规则与读取范围，不把诊断完成写成故障解决", () => {
  const html = render([
    {
      id: "new",
      status: "completed",
      mode: "auto",
      created_at: "now",
      result: {
        version: 2,
        method: "rules",
        model_status: "timeout",
        trigger: "materials_verified",
        duration_ms: 35000,
        sources: [
          {
            file_id: "file",
            name: "diagnostics.zip",
            archive_entry: "logs/recording.log",
            read_bytes: 1200,
            truncated: true,
          },
        ],
        findings: [],
      },
    },
    { id: "old", status: "queued", mode: "auto", created_at: "now", result: { version: 1 } },
  ]);
  assert.match(html, /<details[^>]*open=""/);
  assert.ok(html.includes("v2") && html.includes("模型分析超时 · 已保留规则结果"), html);
  assert.ok(html.includes("logs/recording.log") && html.includes("部分读取"));
  assert.ok(html.includes("执行 35.0 秒") && html.includes("自动初诊"));
  assert.ok(!html.includes("故障已解决"));
});
test("排队与执行有不同文案，材料未到时不伪造日志分析结果", () => {
  const html = render([
    { id: "x", status: "queued", mode: "auto", created_at: "now", result: { materials_status: "awaiting_materials" } },
  ]);
  assert.ok(html.includes("排队中，尚未开始分析"), html);
  assert.ok(html.includes("当前仅分析上报描述"));
});
test("材料未齐时明确等待，不显示模型失败", () => {
  const html = render([
    { id: "x", status: "completed", mode: "auto", created_at: "now", result: { model_status: "awaiting_materials" } },
  ]);
  assert.ok(html.includes("等待日志上传完成，随后自动诊断"));
  assert.ok(!html.includes("模型分析失败"));
});
test("当前报告突出展示，旧报告收进历史区域", () => {
  const html = render([
    {
      id: "new",
      status: "completed",
      mode: "auto",
      created_at: "now",
      result: { version: 4, model_status: "completed", method: "hybrid" },
    },
    {
      id: "old",
      status: "completed",
      mode: "auto",
      created_at: "before",
      result: { version: 3, model_status: "failed" },
    },
  ]);
  assert.ok(html.includes("当前报告"));
  assert.match(html, /<summary[^>]*>历史报告（1）<\/summary>/);
  assert.ok(html.indexOf("当前报告") < html.indexOf("历史报告"));
});

test("模型自评明确不是正确概率，旧报告不伪造分数", () => {
  const row = {
    id: "c",
    status: "completed",
    mode: "auto",
    created_at: "now",
    result: {
      method: "hybrid",
      model_status: "completed",
      model_confidence: 0.82,
      evidence_assessment: "partial",
      confidence_basis: "日志支持连接拒绝，服务状态仍需核对。",
      model_info: { model: "local", engine: "pydantic-ai" },
    },
  };
  const html = render([row]);
  assert.ok(html.includes("模型自评 82%") && html.includes("非正确概率") && html.includes("材料部分支持"));
  assert.ok(html.includes("分析来源"));
  const old = render([{ ...row, result: { method: "hybrid", model_status: "completed" } }]);
  assert.ok(!old.includes("模型自评"));
});

test("已读取材料独立折叠默认展开，评价显示选择及改进说明", () => {
  const html = render([
    {
      id: "review",
      status: "completed",
      feedback: "unhelpful",
      feedback_note: "这是验收，不能认定缺少平台回执",
      created_at: "now",
      result: { version: 1, method: "hybrid", sources: [{ file_id: "f", name: "scene.json", read_bytes: 80 }] },
    },
  ]);
  assert.match(html, /<details[^>]*open=""[^>]*>\s*<summary[^>]*>已读取材料/);
  assert.match(html, /aria-pressed="true"/);
  assert.match(html, /已反馈：需改进/);
  assert.match(html, /这是验收/);
});

test("诊断报告显示严重程度依据与引用原句，空值明确待评估", () => {
  const base = { id: "severity", status: "completed", mode: "auto", created_at: "now" };
  const html = render([
    {
      ...base,
      result: {
        severity_assessment: {
          severity: "major",
          basis: "原始数据完整性拒绝",
          evidence: [{ reference: "FILE-log", quote: "MCAP write failed" }],
        },
      },
    },
  ]);
  for (const value of ["本次判级建议", "严重", "原始数据完整性拒绝", "FILE-log", "MCAP write failed"])
    assert.ok(html.includes(value), value);
  const pending = render([
    { ...base, result: { severity_assessment: { severity: "", basis: "缺少运行证据", evidence: [] } } },
  ]);
  assert.ok(pending.includes("待评估"));
  assert.ok(!pending.includes("undefined"));
});

test("判级方法分别标明模型、材料规则与待评估，旧报告不补造方法", () => {
  const row = { id: "method", status: "completed", mode: "auto", created_at: "now" };
  for (const [method, label] of [
    ["model_verified", "模型判级"],
    ["evidence_rules", "材料规则判级"],
    ["pending", "待评估"],
  ]) {
    const html = render([
      { ...row, result: { severity_assessment: { severity: "major", basis: "按当前材料核验", evidence: [], method } } },
    ]);
    assert.ok(html.includes(label), method);
    assert.ok(html.includes("本次判级建议"));
    if (method === "evidence_rules") assert.ok(!html.includes("模型判级"));
  }
  const old = render([
    { ...row, result: { severity_assessment: { severity: "minor", basis: "旧版依据", evidence: [] } } },
  ]);
  assert.ok(old.includes("旧版依据"));
  assert.ok(!old.includes("模型判级") && !old.includes("材料规则判级") && !old.includes("undefined"));
});
