import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
const walk = (n) =>
  !n || typeof n !== "object" ? [] : Array.isArray(n) ? n.flatMap(walk) : [n, ...walk(n.props?.children)];
function load(file, mocks = {}) {
  const exports = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(`../core/components/quality/${file}.tsx`, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((id) => mocks[id] || require(id), exports);
  return exports;
}
const data = {
  total: 3,
  unclosed: 2,
  by_status: [
    { value: "open", count: 1 },
    { value: "resolved", count: 1 },
    { value: "closed", count: 1 },
  ],
  by_severity: [],
  opened_by_day: [],
};
const common = {
  "./owner-summary": { OwnerSummary: () => null },
  "./owner-metrics": { defectOwnerMetrics: [] },
  react: { ...React, useState: (v) => [v, () => {}] },
  swr: { default: () => ({ data }) },
  "./statistics-display": { Distribution: "Distribution", TrendChart: "TrendChart" },
  "./api": { qualityApi: {} },
  "./types": { statusNames: { open: "待处理", closed: "已关闭" }, severityNames: {} },
  "./defect-report": {
    defectReport: () => ({ awaitingRegression: 1, closed: 1, closedPercent: 33, recentTotal: 0, trend: [] }),
  },
  "./defect-statistics-details": { DefectStatisticsDetails: "Details" },
};
test("四张缺陷统计卡均为可点击入口，图表选择不调用离开统计页的onFilter", () => {
  const exp = load("defect-statistics", common),
    calls = [];
  const tree = exp.DefectStatistics({
    base: "/q/",
    params: new URLSearchParams("panel=statistics&view=assigned_to_me"),
    onFilter: (...v) => calls.push(v),
    onOpenDefect() {},
  });
  assert.equal(walk(tree).filter((n) => n.type === "button" && n.props["aria-label"]?.startsWith("查看")).length, 4);
  walk(tree)
    .find((n) => n.type === "Distribution")
    .props.onSelect("open");
  assert.deepEqual(calls, []);
});

const detailsMocks = {
  react: { ...React, useState: (value) => [value, () => {}] },
  swr: { default: () => ({}) },
  "@plane/utils": { renderNumericDateTime: () => "" },
  "./shared": { Modal: "Modal", Paging: "Paging" },
  "./record-badge": { Badge: "Badge" },
  "./api": { qualityApi: {}, errorMessage: (error) => error.message },
  "./types": { defectDisplayTitle: (title) => title, severityNames: {} },
};
test("明细查询与原筛选取交集且日期保留中国日边界，移除UI分页参数", () => {
  const api = load("defect-statistics-details", detailsMocks);
  const original = new URLSearchParams(
    "panel=statistics&page=9&per_page=5&tab=defects&layout=table&saved_view=v&view=assigned_to_me&device=robot&created_after=2026-11-03&start=2026-11-01&end=2026-11-09&created_before=2026-11-10"
  );
  const { query, empty } = api.defectStatisticsDetailQuery(
    original,
    { title: "未关闭", filters: { exclude_status: "closed" } },
    2
  );
  assert.equal(empty, false);
  assert.equal(query.get("view"), "assigned_to_me");
  assert.equal(query.get("device"), "robot");
  assert.equal(query.get("created_after"), "2026-11-03");
  assert.equal(query.get("created_before"), "2026-11-09");
  assert.equal(query.get("page"), "2");
  assert.equal(query.get("per_page"), "50");
  assert.equal(query.get("exclude_status"), "closed");
  for (const key of ["panel", "tab", "layout", "saved_view", "start", "end"]) assert.equal(query.has(key), false);
  assert.equal(original.get("page"), "9");
  assert.equal(original.get("panel"), "statistics");
  assert.equal(
    api.defectStatisticsDetailQuery(
      new URLSearchParams("status=open"),
      { title: "关闭", filters: { status: "closed" } },
      1
    ).empty,
    true
  );
  assert.equal(
    api.defectStatisticsDetailQuery(
      new URLSearchParams("created_after=2026-11-12"),
      { title: "旧日", filters: { created_after: "2026-11-10", created_before: "2026-11-10" } },
      1
    ).empty,
    true
  );
});
test("明细选择缺陷先关闭弹窗后调用外层打开，关闭不修改统计params", () => {
  const calls = [],
    requests = [];
  const api = load("defect-statistics-details", {
    ...detailsMocks,
    swr: {
      default: (key) => {
        requests.push(key);
        return {
          data: {
            count: 1,
            results: [{ id: "d", code: "Q-D-1", title: "数据异常", status: "resolved", severity: "major" }],
          },
        };
      },
    },
  });
  const params = new URLSearchParams("panel=statistics&view=assigned_to_me&page=4");
  const tree = api.DefectStatisticsDetails({
    base: "/q/",
    params,
    selection: { title: "未关闭", filters: { exclude_status: "closed" } },
    onClose: () => calls.push("close"),
    onOpenDefect: (id) => calls.push(id),
  });
  walk(tree)
    .find((node) => node.type === "button")
    .props.onClick();
  assert.deepEqual(calls, ["close", "d"]);
  assert.match(requests[0], /view=assigned_to_me/);
  assert.equal(params.toString(), "panel=statistics&view=assigned_to_me&page=4");
});

test("已有排除状态与未关闭卡片取交集，不用后一次排除覆盖原范围", () => {
  const api = load("defect-statistics-details", detailsMocks);
  const result = api.defectStatisticsDetailQuery(
    new URLSearchParams("exclude_status=open&view=assigned_to_me"),
    { title: "未关闭", filters: { exclude_status: "closed" } },
    1
  );
  assert.equal(result.empty, false);
  assert.deepEqual(result.query.getAll("exclude_status"), ["open", "closed"]);
  assert.equal(result.query.get("view"), "assigned_to_me");
});

test("卡片选择传对应交集条件和统计数，点击零值也可查看空明细", () => {
  let selected;
  const exp = load("defect-statistics", {
    ...common,
    react: {
      ...React,
      useState: () => [
        undefined,
        (value) => {
          selected = value;
        },
      ],
    },
  });
  const tree = exp.DefectStatistics({
    base: "/q/",
    params: new URLSearchParams("panel=statistics&status=open"),
    onOpenDefect() {},
  });
  const cards = walk(tree).filter((node) => node.type === "button" && node.props["aria-label"]?.startsWith("查看"));
  for (const [index, title, filters, count] of [
    [0, "全部缺陷", {}, 3],
    [1, "未关闭", { exclude_status: "closed" }, 2],
    [2, "待回归", { status: "resolved" }, 1],
    [3, "已关闭", { status: "closed" }, 1],
  ]) {
    cards[index].props.onClick();
    assert.deepEqual(selected, { title, filters, expectedCount: count });
  }
});

test("已关闭卡片直接展示数量和绿色状态，关闭率作为补充", () => {
  const { DefectStatistics } = load("defect-statistics", common);
  const tree = DefectStatistics({ base: "/q/", params: new URLSearchParams() });
  const card = walk(tree).find((n) => n.type === "button" && n.props["aria-label"] === "查看已关闭明细");
  assert.ok(card);
  assert.ok(
    walk(card).some(
      (n) => n.type === "p" && n.props.children === 1 && n.props.className.includes("text-success-primary")
    )
  );
});

test("待评估严重程度按空值计数并用unassessed下钻", () => {
  let selected;
  const exp = load("defect-statistics", {
    ...common,
    "./types": { statusNames: {}, severityNames: { "": "待评估", major: "严重" } },
    react: {
      ...React,
      useState: () => [
        undefined,
        (v) => {
          selected = v;
        },
      ],
    },
    swr: { default: () => ({ data: { ...data, by_severity: [{ value: "", count: 2 }] } }) },
  });
  const tree = exp.DefectStatistics({ base: "/q/", params: new URLSearchParams() });
  const distribution = walk(tree).find((n) => n.type === "Distribution" && n.props.title === "严重程度");
  assert.equal(distribution.props.rows.find((n) => n.key === "").count, 2);
  assert.ok(distribution.props.rows.find((n) => n.key === "").color);
  distribution.props.onSelect("");
  assert.deepEqual(selected, { title: "待评估", filters: { severity: "unassessed" }, expectedCount: 2 });
});
