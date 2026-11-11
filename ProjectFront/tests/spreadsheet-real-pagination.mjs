import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
function load(path, mocks = {}) {
  const api = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((id) => mocks[id] ?? (id === "react/jsx-runtime" ? require(id) : new Proxy({}, { get: () => () => null })), api);
  return api;
}
const ids = (count) => Array.from({ length: count }, (_, i) => `issue-${i + 1}`);
const helper = () =>
  load("../core/components/issues/issue-layouts/spreadsheet/pagination.ts", {
    "../kanban/arrangement": load("../core/components/issues/issue-layouts/kanban/arrangement.ts"),
  });
test("表格总数275而缓存100时仍有14页，不再自动加载", () => {
  const { spreadsheetPageWindow } = helper();
  const page = spreadsheetPageWindow(ids(100), 275, 20, 1);
  assert.equal(page.pageCount, 14);
  assert.equal(page.visibleIds.length, 20);
  assert.doesNotMatch(
    readFileSync(
      new URL("../core/components/issues/issue-layouts/spreadsheet/spreadsheet-table.tsx", import.meta.url),
      "utf8"
    ),
    /useIntersectionObserver/
  );
});
test("表格20/50/100每页，跳275尾页只补取必要100条游标批次", async () => {
  const { loadSpreadsheetPage } = helper();
  for (const size of [20, 50, 100]) {
    let cached = ids(100),
      calls = 0;
    const target = Math.ceil(275 / size);
    const page = await loadSpreadsheetPage(
      target,
      size,
      () => ({ ids: cached, total: 275, hasMore: cached.length < 275 }),
      async () => {
        calls++;
        cached = ids(Math.min(275, cached.length + 100));
      }
    );
    assert.equal(calls, 2);
    assert.deepEqual(page.visibleIds, ids(275).slice((target - 1) * size));
    assert.equal(page.pageSize, size);
  }
});

function hookHarness() {
  let cache = ids(100),
    filters = { priority: "high", order_by: "state__name,-priority" },
    order = "state__name,-priority",
    user = "table-user",
    path = "/w/p/issues";
  const cells = [],
    calls = [];
  let cell = 0,
    fail = false;
  const store = {
    getIssueIds: () => cache,
    getGroupIssueCount: () => 275,
    getIssueLoader: () => undefined,
    getPaginationData: () => ({ nextPageResults: cache.length < 275 }),
  };
  const { useSpreadsheetPagination } = load("../core/components/issues/issue-layouts/spreadsheet/use-pagination.ts", {
    react: {
      useRef: (initial) => {
        const slot = cell++;
        cells[slot] ??= { current: initial };
        return cells[slot];
      },
      useState: (initial) => {
        const slot = cell++;
        cells[slot] ??= initial;
        return [
          cells[slot],
          (value) => {
            cells[slot] = value;
          },
        ];
      },
      useEffect() {},
    },
    "next/navigation": { usePathname: () => path },
    "@/hooks/store/user": { useUser: () => ({ data: { id: user } }) },
    "@/hooks/use-issue-layout-store": {
      useIssueStoreType: () => "project",
      useIssuesStore: () => ({ issues: store, issuesFilter: { appliedFilters: filters } }),
    },
    "@/hooks/use-issues-actions": {
      useIssuesActions: () => ({
        fetchNextIssues: async (group) => {
          calls.push({ group, filters: { ...filters }, order });
          if (fail) throw Error("offline");
          cache = ids(Math.min(275, cache.length + 100));
        },
      }),
    },
    "./pagination": helper(),
  });
  return {
    render() {
      cell = 0;
      return useSpreadsheetPagination(cache, order, 275);
    },
    calls,
    setUser: (value) => {
      user = value;
    },
    setPath: (value) => {
      path = value;
    },
    remount: () => {
      cells.length = 0;
    },
    setFail: (value) => {
      fail = value;
    },
    setFilters: (value) => {
      filters = value;
    },
    setOrder: (value) => {
      order = value;
    },
  };
}
test("真实hook跨100条缓存跳页沿用筛选与多列排序，返回只含目标页", async () => {
  const h = hookHarness();
  await h.render().onPage(14);
  const page = h.render();
  assert.equal(page.page, 14);
  assert.deepEqual(page.visibleIds, ids(275).slice(260));
  assert.equal(page.total, 275);
  assert.equal(h.calls.length, 2);
  for (const call of h.calls) {
    assert.equal(call.group, undefined);
    assert.deepEqual(call.filters, { priority: "high", order_by: "state__name,-priority" });
    assert.equal(call.order, "state__name,-priority");
  }
  await h.render().onPage(2);
  assert.equal(h.calls.length, 2);
  assert.deepEqual(h.render().visibleIds, ids(275).slice(20, 40));
});
test("失败保留页码可重试，页容量/筛选/排序变化均回第一页", async () => {
  const h = hookHarness();
  h.setFail(true);
  await h.render().onPage(14);
  assert.equal(h.render().page, 1);
  assert.equal(h.render().error, true);
  assert.equal(h.render().visibleIds.length, 20);
  h.setFail(false);
  await h.render().onRetry();
  assert.equal(h.render().page, 14);
  h.render().onPageSizeChange(100);
  assert.equal(h.render().page, 1);
  assert.equal(h.render().visibleIds.length, 100);
  await h.render().onPage(3);
  assert.equal(h.render().page, 3);
  h.setFilters({ priority: "urgent" });
  assert.equal(h.render().page, 1);
  assert.equal(h.render().pageSize, 100);
  await h.render().onPage(2);
  h.setOrder("-created_at,name");
  assert.equal(h.render().page, 1);
});
test("表格view仅选择当前页，原列与快捷键交互保持", () => {
  const rows = ids(275).slice(260),
    keyNavigation = () => {};
  const { SpreadsheetView } = load("../core/components/issues/issue-layouts/spreadsheet/spreadsheet-view.tsx", {
    react: { ...React, useRef: () => ({ current: null }), useEffect() {} },
    "mobx-react": { observer: (fn) => fn },
    "@plane/constants": { SPREADSHEET_SELECT_GROUP: "sheet", SPREADSHEET_PROPERTY_LIST: ["key", "state", "assignee"] },
    "@plane/types": { EIssueLayoutTypes: { SPREADSHEET: "spreadsheet" } },
    "@/hooks/store/use-project": { useProject: () => ({ currentProjectDetails: { estimate: null } }) },
    "@/hooks/use-bulk-operation-status": { useBulkOperationStatus: () => true },
    "./pagination": helper(),
    "./use-pagination": {
      useSpreadsheetPagination: () => ({
        visibleIds: rows,
        total: 275,
        page: 14,
        pageSize: 20,
        selectionScope: "scope",
        onPage() {},
        onPageSizeChange() {},
      }),
    },
  });
  const view = SpreadsheetView({
    issueIds: ids(275),
    displayFilters: { order_by: "state__name,-priority" },
    displayProperties: { state: true },
  });
  assert.deepEqual(view.props.children[1].props.entities, { sheet: rows });
  assert.equal(view.props["data-total-count"], 275);
  const children = view.props.children[1].props.children({ handleClearSelection() {} }).props.children;
  const tableProps = children[1].props.children.props;
  assert.deepEqual(tableProps.issueIds, rows);
  assert.equal(tableProps.displayFilters.order_by, "state__name,-priority");
  const { SpreadsheetTable } = load("../core/components/issues/issue-layouts/spreadsheet/spreadsheet-table.tsx", {
    react: { ...React, useRef: (initial) => ({ current: initial }), useCallback: (fn) => fn, useEffect() {} },
    "mobx-react": { observer: (fn) => fn },
    "@/hooks/use-table-keyboard-navigation": { useTableKeyboardNavigation: () => keyNavigation },
  });
  const table = SpreadsheetTable(tableProps);
  assert.equal(table.props.onKeyDown, keyNavigation);
  assert.equal(table.props.children[1].props.children.length, 15);
});

test("筛选刷新卸载表格后仍记住每页条数，不串给列表或其他账号", () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, "localStorage"),
    values = new Map();
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: { getItem: (key) => values.get(key) || null, setItem: (key, value) => values.set(key, value) },
  });
  try {
    const h = hookHarness();
    h.render().onPageSizeChange(50);
    h.remount();
    assert.equal(h.render().pageSize, 50);
    assert.equal(h.render().page, 1);
    assert.equal([...values.keys()][0], "spreadsheet-page-size:table-user:/w/p/issues:project");
  } finally {
    if (original) Object.defineProperty(globalThis, "localStorage", original);
    else delete globalThis.localStorage;
  }
});

test("表格未卸载切换项目或账号时页容量隔离，返回后恢复各自选择", async () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, "localStorage"),
    values = new Map();
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: { getItem: (key) => values.get(key) || null, setItem: (key, value) => values.set(key, value) },
  });
  try {
    const h = hookHarness();
    h.render().onPageSizeChange(50);
    await h.render().onPage(3);
    h.setPath("/w/other/issues");
    assert.equal(h.render().page, 1);
    assert.equal(h.render().pageSize, 20);
    h.render().onPageSizeChange(100);
    h.setUser("another-user");
    assert.equal(h.render().pageSize, 20);
    h.setUser("table-user");
    assert.equal(h.render().pageSize, 100);
    h.setPath("/w/p/issues");
    assert.equal(h.render().pageSize, 50);
  } finally {
    if (original) Object.defineProperty(globalThis, "localStorage", original);
    else delete globalThis.localStorage;
  }
});
