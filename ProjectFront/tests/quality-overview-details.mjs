import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
function load(name, overrides = {}) {
  const exports = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(`../core/components/quality/${name}.tsx`, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )(
    (id) => overrides[id] || (id === "react/jsx-runtime" ? require(id) : new Proxy({}, { get: () => () => null })),
    exports
  );
  return exports;
}
function nodes(tree) {
  return !tree || typeof tree !== "object"
    ? []
    : Array.isArray(tree)
      ? tree.flatMap(nodes)
      : [tree, ...nodes(tree.props?.children)];
}
const OverviewDetails = () => null;
const Distribution = () => null;
test("概览卡片打开本地明细弹窗而不切换tab，关闭保留原概览", () => {
  let selection = null,
    navigations = 0;
  const source = load("quality-summary", {
    react: {
      useState: () => [
        selection,
        (value) => {
          selection = value;
        },
      ],
    },
    "./quality-overview-details": { QualityOverviewDetails: OverviewDetails },
    "./types": { resultNames: { passed: "通过" } },
  });
  const props = {
    base: "/q/",
    report: { summary: {}, definitions: {}, case_count: 2, plan_count: 1, execution_count: 3, open_defects: 1 },
    onNavigate() {
      navigations++;
    },
  };
  let tree = source.QualitySummary(props);
  nodes(tree)
    .find((n) => n.type === "button" && nodes(n).some((c) => c.props?.children === "有效测试计划"))
    .props.onClick();
  assert.equal(selection.kind, "plans");
  assert.equal(navigations, 0);
  tree = source.QualitySummary(props);
  const modal = nodes(tree).find((n) => n.type === OverviewDetails);
  assert.equal(modal.props.base, "/q/");
  modal.props.onClose();
  assert.equal(selection, null);
  assert.equal(navigations, 0);
});
test("pending明细收齐全部计划页再按条目分页，不以计划数替代未执行数", async () => {
  const urls = [];
  const source = load("quality-overview-details", {
    "./api": {
      qualityApi: {
        read: async (url) => {
          urls.push(url);
          return url.includes("page=2")
            ? {
                count: 101,
                results: [
                  {
                    id: "second",
                    name: "第二页",
                    items: [
                      { id: "b", case_id: "caseb", revision: { title: "待执行B", version: 2 }, latest_execution: null },
                    ],
                  },
                ],
              }
            : {
                count: 101,
                results: [
                  {
                    id: "first",
                    name: "第一页",
                    items: [
                      { id: "a", case_id: "casea", revision: { title: "待执行A", version: 1 }, latest_execution: null },
                      { id: "done", revision: { title: "已通过" }, latest_execution: { result: "passed" } },
                    ],
                  },
                ],
              };
        },
      },
    },
  });
  const data = await source.loadOverviewDetails("/q/", { kind: "pending", title: "未执行" }, 1, "");
  assert.equal(data.count, 2);
  assert.equal(data.results.length, 2);
  assert.equal(urls.length, 2);
  assert.ok(urls.every((url) => url.includes("current_only=true")));
});
test("当前结果明细沿用current_only与result，执行记录卡片保留历史范围", async () => {
  const urls = [];
  const source = load("quality-overview-details", {
    "./api": {
      qualityApi: {
        read: async (url) => {
          urls.push(url);
          return { count: 0, results: [] };
        },
      },
    },
  });
  await source.loadOverviewDetails("/q/", { kind: "executions", title: "失败", result: "failed" }, 1, "");
  await source.loadOverviewDetails("/q/", { kind: "executions", title: "执行历史" }, 1, "");
  await source.loadOverviewDetails("/q/", { kind: "defects", title: "未关闭" }, 1, "");
  assert.ok(urls[0].includes("current_only=true") && urls[0].includes("result=failed"));
  assert.ok(!urls[1].includes("current_only"));
  assert.ok(urls[2].includes("exclude_status=closed"));
});
test("明细打开计划只通知覆盖详情，不关闭原明细或重置筛选", () => {
  let opened,
    closed = 0,
    stateIndex = 0;
  const source = load("quality-overview-details", {
    react: { useState: () => [stateIndex++ === 0 ? 2 : "已有搜索", () => {}] },
    swr: {
      default: () => ({
        data: { count: 21, results: [{ id: "execution", title: "执行结果", target: { kind: "plan", id: "plan-id" } }] },
      }),
    },
  });
  const tree = source.QualityOverviewDetails({
    base: "/q/",
    selection: { kind: "executions", title: "执行记录" },
    onClose() {
      closed++;
    },
    onOpenRecord(value) {
      opened = value;
    },
  });
  nodes(tree)
    .find((n) => n.type === "button" && n.props.onClick && nodes(n).some((child) => child === n))
    .props.onClick();
  assert.deepEqual(opened, { kind: "plan", id: "plan-id" });
  assert.equal(closed, 0);
  assert.equal(nodes(tree).find((n) => n.type === "input").props.value, "已有搜索");
});

test("已关闭缺陷和人工结果按对应条件查询明细", async () => {
  const urls = [];
  const source = load("quality-overview-details", {
    "./api": {
      qualityApi: {
        read: async (url) => {
          urls.push(url);
          return { count: 0, results: [] };
        },
      },
    },
  });
  await source.loadOverviewDetails("/q/", { kind: "defects", title: "已关闭缺陷", result: "closed" }, 1, "");
  await source.loadOverviewDetails("/q/", { kind: "manual", title: "人工验证 · 失败", result: "failed" }, 1, "");
  assert.equal(new URL(urls[0], "https://test").searchParams.get("status"), "closed");
  assert.ok(!urls[0].includes("exclude_status"));
  assert.equal(new URL(urls[1], "https://test").searchParams.get("result"), "failed");
  assert.ok(urls[1].includes("mode=manual") && urls[1].includes("current_only=true"));
});

test("已关闭缺陷卡片和人工结果分布均打开统一明细弹窗", () => {
  let selection = null;
  const source = load("quality-summary", {
    react: {
      useState: () => [
        null,
        (next) => {
          selection = next;
        },
      ],
    },
    "./statistics-display": { Distribution },
    "./types": { resultNames: { passed: "通过", failed: "失败" } },
  });
  const tree = source.QualitySummary({
    base: "/q/",
    report: {
      summary: {},
      definitions: {},
      case_count: 0,
      plan_count: 0,
      execution_count: 0,
      open_defects: 1,
      closed_defects: 2,
      manual_verification: { total: 2, passed: 1, failed: 1 },
    },
  });
  const closed = nodes(tree).find(
    (n) => n.type === "button" && nodes(n).some((c) => c.props?.children === "已关闭缺陷")
  );
  assert.ok(closed);
  closed.props.onClick();
  assert.deepEqual(selection, { kind: "defects", title: "已关闭缺陷", result: "closed" });
  const manual = nodes(tree).find((n) => n.type === Distribution && n.props.title === "人工验证结果");
  assert.ok(manual && manual.props.showStatus);
  manual.props.onSelect("failed");
  assert.deepEqual(selection, { kind: "manual", title: "人工验证 · 失败", result: "failed" });
});

test("缺陷用例执行明细打开原缺陷，普通执行仍打开原计划", async () => {
  const source = load("quality-overview-details", {
    "./api": {
      qualityApi: {
        read: async () => ({
          count: 2,
          results: [
            { id: "new", defect_id: "defect-1", plan_id: "plan-1", case_title: "缺陷用例", result: "passed" },
            { id: "old", plan_id: "ordinary", case_title: "普通用例", result: "passed" },
          ],
        }),
      },
    },
  });
  const data = await source.loadOverviewDetails("/q/", { kind: "executions", title: "通过", result: "passed" }, 1, "");
  assert.deepEqual(
    data.results.map((row) => row.target),
    [
      { kind: "defect", id: "defect-1" },
      { kind: "plan", id: "ordinary" },
    ]
  );
});
