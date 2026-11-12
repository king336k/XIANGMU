import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const source = (file) => readFileSync(new URL(`../core/${file}`, import.meta.url), "utf8");

function method(file, name, values = {}) {
  const raw = source(file);
  const tree = ts.createSourceFile(file, raw, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
  let target;
  function visit(node) {
    if (ts.isPropertyDeclaration(node) && node.name.getText(tree) === name) {
      target = ts.isCallExpression(node.initializer) ? node.initializer.arguments[0] : node.initializer;
    }
    ts.forEachChild(node, visit);
  }
  visit(tree);
  assert.ok(target, `${file} ${name}`);
  const code = ts.transpileModule(`const target = ${target.getText(tree)};`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText;
  return new Function(...Object.keys(values), `return function(){${code};return target;};`)(...Object.values(values));
}

function paramsFor(file, applied, options = {}, cursor, group, subgroup) {
  const holder = {
    rootIssueStore: { currentUserId: "actor" },
    getAppliedFilters: () => applied,
    getPaginationParams: (filters, opts, next, groupId, subGroupId) => ({
      ...filters,
      ...opts,
      cursor: next,
      group_id: groupId,
      sub_group_id: subGroupId,
    }),
  };
  const get = method(file, "getFilterParams", { STATIC_VIEW_TYPES: [] }).call(holder);
  return get(options, "project", cursor, group, subgroup);
}

test("项目任务列表各布局和分组续页强制传服务端task筛选，保留用户过滤与游标", () => {
  for (const layout of ["list", "kanban", "spreadsheet", "calendar", "gantt_chart"]) {
    const applied = { layout, state: "state-id", business_kind: "requirement" };
    const result = paramsFor(
      "store/issue/project/filter.store.ts",
      applied,
      { per_page: "20" },
      "next-cursor",
      "group",
      "subgroup"
    );
    assert.equal(result.business_kind, "task");
    assert.equal(result.state, "state-id");
    assert.equal(result.layout, layout);
    assert.equal(result.cursor, "next-cursor");
    assert.equal(result.group_id, "group");
    assert.equal(result.sub_group_id, "subgroup");
    assert.equal(applied.business_kind, "requirement");
  }
});

test("工作空间综合列表不自动排除需求，保持原筛选契约", () => {
  const result = paramsFor("store/issue/workspace/filter.store.ts", { state: "open" });
  assert.equal(result.business_kind, undefined);
  assert.equal(result.state, "open");
});

test("保存后的项目任务视图各布局及分组续页同样保持服务端task范围", () => {
  for (const layout of ["list", "kanban", "spreadsheet", "calendar", "gantt_chart"]) {
    const result = paramsFor(
      "store/issue/project-views/filter.store.ts",
      { layout, state: "state-id", business_kind: "all" },
      { per_page: "20" },
      "next",
      "group",
      "subgroup"
    );
    assert.equal(result.business_kind, "task");
    assert.equal(result.state, "state-id");
    assert.equal(result.cursor, "next");
    assert.equal(result.group_id, "group");
    assert.equal(result.sub_group_id, "subgroup");
  }
});

test("已保存的项目视图首屏和续页将task参数传到同一后端，不过滤客户端响应", async () => {
  const calls = [];
  const response = { total_count: 9, results: [{ id: "task-id" }] };
  const holder = {
    paginationOptions: { per_page: "20" },
    issueFilterStore: {
      getFilterParams: (...args) =>
        paramsFor("store/issue/project-views/filter.store.ts", { state: "open" }, args[0], args[2], args[3], args[4]),
    },
    issueService: {
      getIssues: async (workspace, project, params) => {
        calls.push(params);
        return response;
      },
    },
    controller: { signal: undefined },
    setLoader() {},
    clear() {},
    getPaginationData: () => ({ nextPageResults: true }),
    getNextCursor: () => "next",
    onfetchIssues(value) {
      assert.equal(value, response);
    },
    onfetchNexIssues(value) {
      assert.equal(value, response);
    },
  };
  const first = method("store/issue/project-views/issue.store.ts", "fetchIssues", { runInAction: (fn) => fn() }).call(
    holder
  );
  const next = method("store/issue/project-views/issue.store.ts", "fetchNextIssues").call(holder);
  await first("workspace", "project", "saved-view", "init-loader", holder.paginationOptions);
  await next("workspace", "project", "saved-view", "group", "subgroup");
  assert.equal(calls.length, 2);
  assert.ok(calls.every((params) => params.business_kind === "task"));
  assert.equal(calls[1].cursor, "next");
  assert.equal(response.total_count, 9);
});

test("项目首屏与分组下一页使用同一task参数并直接消费服务端总数", async () => {
  const calls = [];
  const response = { total_count: 7, results: [{ id: "task-1" }] };
  const holder = {
    paginationOptions: { per_page: "20" },
    issueFilterStore: {
      getFilterParams: (...args) =>
        paramsFor("store/issue/project/filter.store.ts", { state: "open" }, args[0], args[2], args[3], args[4]),
    },
    issueService: {
      getIssues: async (workspace, project, params) => {
        calls.push(params);
        return response;
      },
    },
    controller: { signal: undefined },
    setLoader() {},
    clear() {},
    getPaginationData: () => ({ nextPageResults: true }),
    getNextCursor: () => "next-cursor",
    onfetchIssues(value) {
      assert.equal(value, response);
    },
    onfetchNexIssues(value) {
      assert.equal(value, response);
    },
  };
  const first = method("store/issue/project/issue.store.ts", "fetchIssues", { runInAction: (fn) => fn() }).call(holder);
  const next = method("store/issue/project/issue.store.ts", "fetchNextIssues").call(holder);
  await first("workspace", "project", "init-loader", holder.paginationOptions);
  await next("workspace", "project", "group", "subgroup");
  assert.equal(calls.length, 2);
  assert.ok(calls.every((params) => params.business_kind === "task" && params.state === "open"));
  assert.equal(calls[1].cursor, "next-cursor");
  assert.equal(response.total_count, 7);
});

test("项目任务和需求页面明确分开，工作总览保留跨项目综合名称", () => {
  const nav = JSON.parse(
    readFileSync(new URL("../../packages/i18n/src/locales/zh-CN/navigation.json", import.meta.url), "utf8")
  );
  const common = JSON.parse(
    readFileSync(new URL("../../packages/i18n/src/locales/zh-CN/common.json", import.meta.url), "utf8")
  );
  assert.equal(nav.sidebar.work_items, "任务");
  assert.equal(common.workspace_work_overview, "工作总览");
  assert.match(source("components/issues/header.tsx"), /label="任务"/);
  assert.match(source("components/issues/header.tsx"), /新建任务/);
  const requirements = source("components/quality/requirements-workbench.tsx");
  assert.match(requirements, /platform-page-title">需求</);
  assert.match(requirements, /查看任务/);
  assert.doesNotMatch(requirements, /需求管理|全部工作项/);
});

test("项目侧栏与页签的六个主要入口按需求到文档顺序一致", () => {
  const expected = ["requirements", "work_items", "defects", "quality", "versions", "knowledge"];
  for (const file of [
    "components/workspace/sidebar/project-navigation.tsx",
    "components/navigation/use-navigation-items.ts",
  ]) {
    const raw = source(file);
    const tree = ts.createSourceFile(file, raw, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    let callback;
    function visit(node) {
      if (ts.isVariableDeclaration(node) && node.name.getText(tree) === "baseNavigation")
        callback = node.initializer.arguments[0];
      ts.forEachChild(node, visit);
    }
    visit(tree);
    assert.ok(callback);
    const icons = [...new Set([...raw.matchAll(/icon: (\w+)/g)].map((match) => match[1]))];
    const code = ts.transpileModule(`const fn=${callback.getText(tree)};`, {
      compilerOptions: { target: ts.ScriptTarget.ES2022 },
    }).outputText;
    const fn = new Function("EUserPermissions", "project", ...icons, `${code};return fn;`)(
      { ADMIN: 20, MEMBER: 15, GUEST: 5 },
      {},
      ...icons.map(() => () => null)
    );
    const items = fn("workspace", "project")
      .toSorted((a, b) => a.sortOrder - b.sortOrder)
      .filter((item) => expected.includes(item.key));
    assert.deepEqual(
      items.map((item) => item.key),
      expected,
      file
    );
  }
});

test("所有项目导航默认页都能映射到自身路径，版本迭代不会回落任务页", () => {
  const raw = source("components/navigation/tab-navigation-utils.ts");
  const api = {};
  new Function(
    "exports",
    ts.transpileModule(raw, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } })
      .outputText
  )(api);
  for (const [key, path] of Object.entries({
    requirements: "requirements",
    work_items: "issues",
    defects: "defects",
    quality: "quality",
    versions: "versions",
    knowledge: "knowledge",
    cycles: "cycles",
    modules: "modules",
    views: "views",
    pages: "pages",
    intake: "intake",
  })) {
    assert.equal(api.getTabUrl("workspace", "project", key), `/workspace/projects/project/${path}`, key);
  }
  assert.equal(api.getTabUrl("workspace", "project", "unknown"), "/workspace/projects/project/issues");
});

test("统计的需求任务综合数据不误用项目任务专属标题", () => {
  assert.match(source("components/analytics/tabs.tsx"), /label: t\("work_items"\)/);
  assert.match(source("components/analytics/work-items/root.tsx"), /i18nTitle="work_items"/);
});

test("项目任务浏览器标题明确为任务，不复用综合工作项标题", () => {
  const raw = readFileSync(
    new URL(
      "../app/(all)/[workspaceSlug]/(projects)/projects/(detail)/[projectId]/issues/(list)/page.tsx",
      import.meta.url
    ),
    "utf8"
  );
  assert.match(raw, /- 任务/);
  assert.doesNotMatch(raw, /t\("issue.label"/);
});

test("新默认个人导航按草稿便笺排序，不修改既有用户的显式偏好", () => {
  const raw = readFileSync(new URL("../../packages/types/src/navigation-preferences.ts", import.meta.url), "utf8");
  const api = {};
  new Function("exports", ts.transpileModule(raw, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText)(
    api
  );
  assert.equal(api.DEFAULT_PERSONAL_PREFERENCES.items.stickies.enabled, true);
  assert.ok(
    api.DEFAULT_PERSONAL_PREFERENCES.items.drafts.sort_order <
      api.DEFAULT_PERSONAL_PREFERENCES.items.stickies.sort_order
  );
  const hook = source("hooks/use-navigation-preferences.ts");
  assert.match(hook, /storePreferences\.stickies\?\.is_pinned \?\? DEFAULT_PERSONAL_PREFERENCES/);
  assert.match(hook, /storePreferences\.stickies\?\.sort_order \?\? DEFAULT_PERSONAL_PREFERENCES/);
});
