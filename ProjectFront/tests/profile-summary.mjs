import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const api = {};
new Function(
  "exports",
  ts.transpileModule(readFileSync(new URL("../core/components/profile/overview/links.ts", import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
)(api);
test("统计下钻清空旧条件，限定当前用户和合法的状态、优先级及项目", () => {
  const href = api.profileWorkItemsHref("w", "u", "assigned", {
    state_group: "completed",
    priority: "high",
    project_id: "b3852ff2-5331-4967-997a-656d20f9841e",
  });
  assert.equal(href.split("?")[0], "/w/profile/u/assigned/");
  assert.deepEqual(api.profileSummaryFilters(new URL(href, "http://localhost").searchParams), {
    state_group__in: "completed",
    priority__in: "high",
    project_id__in: "b3852ff2-5331-4967-997a-656d20f9841e",
  });
  assert.equal(api.profileSummaryFilters(new URLSearchParams("state_group=completed")), undefined);
  assert.deepEqual(api.profileSummaryFilters(new URLSearchParams("from=summary")), {});
  assert.deepEqual(
    api.profileSummaryFilters(
      new URLSearchParams("from=summary&state_group=__proto__&priority=constructor&project_id=other&pending=1")
    ),
    { state_group__in: "backlog,unstarted,started" }
  );
});
test("所有内置状态和优先级以业务中文显示，统计卡片有实际跳转", () => {
  assert.deepEqual(Object.values(api.profileStateLabels), ["待排期", "待开始", "进行中", "已完成", "已取消"]);
  for (const name of ["workload", "state-distribution", "priority-distribution"]) {
    const source = readFileSync(new URL(`../core/components/profile/overview/${name}.tsx`, import.meta.url), "utf8");
    assert.doesNotMatch(source, /STATE_GROUPS\[.*\]\.label|capitalizeFirstLetter|"Count"|<a>/);
    assert.match(source, /profileWorkItemsHref/);
  }
});

test("右侧项目统计和活动文案不输出内部英文，完成率只用负责与完成数量", () => {
  const source = readFileSync(new URL("../core/components/profile/sidebar.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(source, /\bCreated\b|\bAssigned\b|\bDue\b|\bCompleted\b|const totalIssues/);
  assert.match(source, /profileWorkItemsHref/);
  assert.match(source, /project.completed_issues \/ project.assigned_issues/);
});

test("任务与需求使用同一标签结构、边框、字号和字重，仅底色和文字颜色区分", () => {
  const React = require("react"),
    exports = {};
  const source = readFileSync(new URL("../core/components/quality/work-item-kind.tsx", import.meta.url), "utf8");
  new Function(
    "require",
    "exports",
    ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } })
      .outputText
  )((id) => {
    if (id === "swr") return { default: () => ({ data: { requirement_sequences: [2] } }) };
    if (id === "react-router") return { useParams: () => ({ workspaceSlug: "w" }) };
    if (id === "react/jsx-runtime") return require(id);
    if (id === "./api") return { qualityApi: {} };
    return React;
  }, exports);
  const task = exports.WorkItemKind({ projectId: "p", sequence: 1 }),
    need = exports.WorkItemKind({ projectId: "p", sequence: 2 });
  assert.equal(task.type, "span");
  assert.equal(need.type, "span");
  for (const cls of ["border-subtle", "text-10", "font-normal", "leading-none"]) {
    assert.ok(task.props.className.includes(cls));
    assert.ok(need.props.className.includes(cls));
  }
});

test("统计数字包含子任务时，下钻不受旧的隐藏子任务设置影响且不改写保存偏好", async () => {
  const storeApi = {};
  const source = readFileSync(new URL("../core/store/issue/profile/filter.store.ts", import.meta.url), "utf8");
  new Function(
    "require",
    "exports",
    ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } })
      .outputText
  )((id) => {
    if (id === "../helpers/issue-filter-helper.store") return { IssueFilterHelperStore: function () {} };
    if (id === "mobx-utils") return { computedFn: (fn) => fn };
    if (id === "mobx")
      return { makeObservable() {}, runInAction: (fn) => fn(), action: {}, computed: {}, observable: {} };
    if (id === "@plane/types") return { EIssuesStoreType: { PROFILE: "profile" } };
    if (id === "@/services/issue_filter.service") return { IssueFiltersService: function () {} };
    if (id === "@plane/constants" || id === "@plane/utils") return {};
    return require(id);
  }, storeApi);
  const store = new storeApi.ProfileIssuesFilter({});
  const saved = { rich_filters: { priority__in: "low" }, display_filters: { layout: "list", sub_issue: false } };
  store.filters = {};
  store.handleIssuesLocalFilters = { get: () => saved, set: () => assert.fail("统计入口不写入保存偏好") };
  store.computedDisplayFilters = (x) => ({ ...x });
  store.computedDisplayProperties = (x) => x;
  await store.fetchFilters("w", "u", {});
  assert.equal(store.filters.u.displayFilters.sub_issue, true);
  assert.equal(saved.display_filters.sub_issue, false);
  assert.deepEqual(store.filters.u.richFilters, {});
  await store.fetchFilters("w", "u");
  assert.equal(store.filters.u.displayFilters.sub_issue, false);
});
