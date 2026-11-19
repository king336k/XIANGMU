import { AgentProcessingBadge } from "./agent-processing-fixture.js";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
function load(name, overrides = {}) {
  const code = ts.transpileModule(
    readFileSync(new URL(`../core/components/quality/${name}.tsx`, import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }
  ).outputText;
  const exports = {};
  new Function("require", "exports", code)(
    (id) => (id === "./agent-processing-badge" ? { AgentProcessingBadge } : overrides[id] || require(id)),
    exports
  );
  return exports;
}
const names = {
  statusNames: { open: "待处理", in_progress: "处理中", resolved: "待回归", closed: "已关闭" },
  resultNames: {},
  severityNames: { critical: "致命", major: "严重", minor: "一般", trivial: "轻微" },
};
test("处理状态与严重程度的彩色标签都保留准确文字", () => {
  const { Badge } = load("record-badge", { "./types": names });
  for (const [value, tone] of [
    ["open", "warning"],
    ["in_progress", "accent"],
    ["closed", "success"],
    ["critical", "danger"],
    ["major", "warning"],
    ["minor", "accent"],
    ["trivial", "layer-1"],
  ]) {
    const html = renderToStaticMarkup(React.createElement(Badge, { value }));
    assert.ok(html.includes(tone), html);
    assert.ok(html.includes(names.statusNames[value] || names.severityNames[value]), html);
  }
});
test("列表、表格、看板统一用彩色状态和严重程度，不依赖单独详情页", () => {
  const badge = load("record-badge", { "./types": names });
  const { RecordPresentation } = load("record-presentation", {
    "./record-badge": badge,
    "./table-header-filter": { TableHeaderFilter: ({ label }) => label },
  });
  const rows = [
    {
      id: "a",
      title: "上传问题",
      status: "in_progress",
      statusName: "处理中",
      severity: "major",
      values: ["严重", "张工", "v2"],
    },
  ];
  for (const layout of ["list", "table", "board"]) {
    const html = renderToStaticMarkup(
      React.createElement(RecordPresentation, {
        rows,
        layout,
        kind: "defects",
        columns: ["严重程度", "负责人", "影响版本"],
        onOpen() {},
      })
    );
    assert.ok(html.includes("bg-accent-subtle") && html.includes("bg-warning-subtle"), html);
    assert.ok(html.includes("张工") && html.includes("上传问题"));
  }
});
test("列表状态动作只打开该记录的处理入口，不调用详情动作", () => {
  const badge = load("record-badge", { "./types": names });
  const { RecordPresentation } = load("record-presentation", {
    "./record-badge": badge,
    "./table-header-filter": { TableHeaderFilter: ({ label }) => label },
  });
  const opened = [],
    updated = [];
  const tree = RecordPresentation({
    rows: [{ id: "a", title: "问题A", status: "open", statusName: "待处理", severity: "major", values: ["严重"] }],
    layout: "list",
    kind: "defects",
    columns: [],
    onOpen: (id) => opened.push(id),
    canChangeStatus: () => true,
    onStatusChange: (id) => updated.push(id),
  });
  clickMatching(tree, ["更新处理状态：问题A"]);
  assert.deepEqual(updated, ["a"]);
  assert.deepEqual(opened, []);
});
test("严重程度和负责人在三种布局均可独立操作，点击不打开详情", () => {
  const badge = load("record-badge", { "./types": names });
  const { RecordPresentation } = load("record-presentation", {
    "./record-badge": badge,
    "./table-header-filter": { TableHeaderFilter: ({ label }) => label },
  });
  for (const layout of ["list", "table", "board"]) {
    const changed = [];
    const tree = RecordPresentation({
      rows: [
        {
          id: "a",
          title: "问题A",
          status: "open",
          statusName: "待处理",
          severity: "major",
          values: ["严重", "未指派", "v1"],
        },
      ],
      layout,
      kind: "defects",
      columns: ["严重程度", "负责人", "影响版本"],
      onOpen: () => assert.fail("不应打开详情"),
      canChangeField: () => true,
      onFieldChange: (id, field) => changed.push([id, field]),
    });
    clickMatching(tree, ["调整严重程度：问题A", "指派负责人：问题A"]);
    assert.deepEqual(
      changed,
      [
        ["a", "severity"],
        ["a", "assignee"],
      ],
      layout
    );
  }
});

function clickMatching(node, labels) {
  if (!node || typeof node !== "object") return;
  if (Array.isArray(node)) {
    node.forEach((item) => clickMatching(item, labels));
    return;
  }
  if (labels.includes(node.props?.["aria-label"])) node.props.onClick();
  clickMatching(node.props?.children, labels);
}

test("DAQ来源分类以中文显示，保留原始业务标题内容", () => {
  const source = readFileSync(new URL("../core/components/quality/types.ts", import.meta.url), "utf8");
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  new Function("exports", code)(exports);
  assert.equal(exports.defectDisplayTitle("DataAnomaly: 上传后缺少日志"), "数据异常：上传后缺少日志");
  assert.equal(exports.defectDisplayTitle("页面提示调整"), "页面提示调整");
});

test("真实严重程度字典包含灰色待评估，不借用严重默认值", () => {
  const exp = {};
  new Function(
    "exports",
    ts.transpileModule(readFileSync(new URL("../core/components/quality/types.ts", import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS },
    }).outputText
  )(exp);
  assert.equal(exp.severityNames[""], "待评估");
  const { Badge } = load("record-badge", { "./types": { ...names, severityNames: exp.severityNames } });
  const html = renderToStaticMarkup(React.createElement(Badge, { value: "" }));
  assert.ok(html.includes("待评估") && html.includes("text-secondary"));
  assert.ok(!html.includes("text-warning-primary"));
});

test("空严重程度在三种布局保持待评估标签和独立编辑入口", () => {
  const severityNames = { ...names.severityNames, "": "待评估" };
  const badge = load("record-badge", { "./types": { ...names, severityNames } });
  const { RecordPresentation } = load("record-presentation", {
    "./record-badge": badge,
    "./table-header-filter": { TableHeaderFilter: ({ label }) => label },
  });
  for (const layout of ["list", "table", "board"]) {
    const changed = [];
    const props = {
      rows: [{ id: "pending", title: "待判级反馈", status: "open", severity: "", values: ["待评估", "技术员", "v1"] }],
      layout,
      kind: "defects",
      columns: ["严重程度", "负责人", "影响版本"],
      onOpen() {},
      canChangeField: () => true,
      onFieldChange: (id, field) => changed.push([id, field]),
    };
    const tree = RecordPresentation(props);
    clickMatching(tree, ["调整严重程度：待判级反馈", "指派负责人：待判级反馈"]);
    assert.deepEqual(
      changed,
      [
        ["pending", "severity"],
        ["pending", "assignee"],
      ],
      layout
    );
    const html = renderToStaticMarkup(React.createElement(RecordPresentation, props));
    assert.ok(html.includes("待评估"), layout);
  }
});
