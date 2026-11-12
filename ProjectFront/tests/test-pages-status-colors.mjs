import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const nodes = (tree) =>
  !tree || typeof tree !== "object"
    ? []
    : Array.isArray(tree)
      ? tree.flatMap(nodes)
      : [tree, ...nodes(tree.props?.children)];
const Badge = () => null;
const stubs = new Map();
const stub = (name) => {
  if (!stubs.has(name)) stubs.set(name, () => null);
  return stubs.get(name);
};
const names = {
  passed: "通过",
  failed: "失败",
  blocked: "阻塞",
  inconclusive: "无法判定",
  skipped: "跳过",
  pending: "未执行",
};
function load(file, overrides = {}) {
  const api = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(`../core/components/quality/${file}.tsx`, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
    }).outputText
  )((id) => {
    if (id in overrides) return overrides[id];
    if (id === "react/jsx-runtime" || id === "uuid") return require(id);
    if (id === "react") return { useState: (v) => [typeof v === "function" ? v() : v, () => {}] };
    if (id === "swr") return { default: () => ({ mutate: async () => {} }) };
    if (id === "./record-badge" || id === "./shared")
      return {
        Badge,
        fieldClass: "field",
        Field: stub("Field"),
        Modal: stub("Modal"),
        Empty: stub("Empty"),
        Paging: stub("Paging"),
      };
    if (id === "./types")
      return {
        resultNames: names,
        reasonNames: {},
        priorityNames: {},
        planStatusNames: { review: "待验收", running: "执行中" },
        can: () => false,
      };
    if (id === "@plane/utils") return { renderNumericDateTime: String };
    return new Proxy({}, { get: (_, key) => stub(key) });
  }, api);
  return api;
}
const summary = {
  total: 8,
  executed: 6,
  passed: 3,
  failed: 1,
  blocked: 1,
  inconclusive: 1,
  skipped: 0,
  pending: 2,
  execution_rate: 75,
  pass_rate: 50,
};
test("测试计划列表和详情的结果计数复用状态Badge，筛选当前项为蓝色", () => {
  const plan = { id: "p", name: "计划", managed: true, status: "review", summary, items: [], business_roles: [] };
  const list = load("record-lists").PlanList({ rows: [plan], onSelect() {} });
  assert.ok(nodes(list).some((n) => n.type === Badge && n.props.value === "failed" && n.props.label.includes("1")));
  const detail = load("plan-detail").PlanDetail({
    base: "/q/",
    value: plan,
    context: {},
    canWrite: false,
    onBack() {},
    onSaved: async () => {},
  });
  for (const value of Object.keys(names))
    assert.ok(
      nodes(detail).some(
        (n) =>
          n.type === Badge &&
          n.props.value === (summary[value] ? value : "neutral") &&
          n.props.label === `${names[value]} ${summary[value]}`
      ),
      value
    );
  const all = nodes(detail).find((n) => n.type === "button" && n.props["aria-pressed"]);
  assert.match(all.props.className, /bg-accent-subtle/);
});
test("报告列表显示真实结论Badge，无结论保持待验收", () => {
  const reports = [
    { id: "a", name: "报告A", conclusion: { result: "passed" } },
    { id: "b", name: "报告B", conclusion: { result: "failed" } },
    { id: "c", name: "报告C" },
  ];
  const { ReportsPanel } = load("reports-panel", {
    swr: {
      default: (url) => ({
        data: url?.includes("?") ? { count: reports.length, results: reports } : undefined,
        mutate: async () => {},
      }),
    },
  });
  const badges = nodes(ReportsPanel({ base: "/q/", context: {} })).filter((n) => n.type === Badge);
  assert.deepEqual(
    badges.map((n) => n.props.value),
    ["passed", "failed", "review"]
  );
});
test("概览结果分布和数量使用同一语义状态，未执行用中性灰", () => {
  const { QualitySummary } = load("quality-summary");
  const tree = QualitySummary({
    report: { summary, definitions: {}, case_count: 3, plan_count: 2, execution_count: 6, open_defects: 1 },
  });
  const distribution = nodes(tree).find((n) => n.type === stub("Distribution"));
  assert.equal(distribution.props.showStatus, true);
  const byKey = Object.fromEntries(distribution.props.rows.map((row) => [row.key, row]));
  assert.equal(byKey.passed.color, "var(--text-color-success-primary)");
  assert.equal(byKey.failed.color, "var(--text-color-danger-primary)");
  assert.equal(byKey.pending.color, "var(--text-color-secondary)");
  const { Distribution } = load("statistics-display");
  const rendered = Distribution({ ...distribution.props });
  assert.ok(nodes(rendered).some((n) => n.type === Badge && n.props.value === "passed"));
  assert.ok(nodes(rendered).some((n) => n.type === "strong" && n.props.style?.color === byKey.passed.color));
});
test("用例库模块名恰为passed仍是普通模块，不显示全局执行结果色", () => {
  const { RecordPresentation } = load("record-presentation");
  for (const layout of ["list", "table", "board"]) {
    const tree = RecordPresentation({
      kind: "cases",
      layout,
      rows: [{ id: "c", title: "普通用例", status: "passed", statusName: "passed", values: [] }],
      columns: [],
      onOpen() {},
    });
    const badges = nodes(tree).filter((n) => n.type === Badge);
    assert.ok(badges.length > 0);
    assert.ok(
      badges.every((n) => n.props.value === "neutral"),
      layout
    );
    assert.ok(
      badges.every((n) => n.props.label === "passed"),
      layout
    );
  }
});
test("用例集发布状态与草稿归档复用Badge，列表与表格一致", () => {
  const { AssetsPanel } = load("assets-panel");
  const rows = [
    { id: "s", name: "草稿", published: false, items: [], edit_version: 1 },
    { id: "a", name: "归档", published: true, archived_at: "2026-11-12", items: [], edit_version: 1 },
  ];
  const props = { base: "/q/", kind: "suites", rows, context: {}, onSaved: async () => {} };
  const list = AssetsPanel(props);
  assert.deepEqual(
    nodes(list)
      .filter((n) => n.type === Badge)
      .map((n) => n.props.value),
    ["draft", "archived"]
  );
  const table = AssetsPanel({ ...props, layout: "table" });
  assert.deepEqual(
    nodes(table)
      .find((n) => n.type === stub("RecordPresentation"))
      .props.rows.map((row) => row.status),
    ["draft", "archived"]
  );
});
