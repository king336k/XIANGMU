import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
function load(path, mocks = {}) {
  const exports = {};
  const code = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  new Function("require", "exports", code)((id) => mocks[id] ?? require(id), exports);
  return exports;
}
const source = () =>
  readFileSync(new URL("../core/components/issues/issue-layouts/list/list-group.tsx", import.meta.url), "utf8");
const ids = (count) => Array.from({ length: count }, (_, index) => `work-${index + 1}`);
const paging = () =>
  load("../core/components/issues/issue-layouts/list/pagination.ts", {
    "../kanban/arrangement": load("../core/components/issues/issue-layouts/kanban/arrangement.ts"),
  });
test("列表不再通过滚动自动请求，渲染的是当前页", () => {
  assert.doesNotMatch(source(), /useIntersectionObserver/);
  assert.match(source(), /issueIds=\{pageWindow.visibleIds\}/);
});
test("分组默认10条、未分组20条，相邻页和尾页不追加前页", () => {
  const { listPageWindow } = paging();
  assert.deepEqual(listPageWindow(ids(55), 55, true, 2).visibleIds, ids(55).slice(10, 20));
  const plain = listPageWindow(ids(45), 45, false, 3);
  assert.equal(plain.pageCount, 3);
  assert.deepEqual(plain.visibleIds, ids(45).slice(40));
  assert.deepEqual([plain.from, plain.to], [41, 45]);
  assert.equal(listPageWindow(ids(6), 6, true, 5).page, 1);
});
test("跳转只补取目标组必要批次，已缓存页不取数", async () => {
  const { loadListPage } = paging();
  let loaded = ids(50),
    calls = 0;
  const snapshot = () => ({ ids: loaded, total: 175, hasMore: loaded.length < 175 });
  const loadMore = async () => {
    calls++;
    loaded = ids(Math.min(175, loaded.length + 50));
  };
  const page = await loadListPage(7, true, snapshot, loadMore);
  assert.equal(calls, 1);
  assert.equal(page.page, 7);
  assert.deepEqual(page.visibleIds, ids(70).slice(60));
  await loadListPage(2, true, snapshot, loadMore);
  assert.equal(calls, 1);
  await loadListPage(16, true, snapshot, loadMore);
  assert.equal(calls, 3);
});
test("失败和无进展保留原页，重试可以恢复", async () => {
  const { loadListPage } = paging();
  let loaded = ids(50),
    currentPage = 1;
  const snapshot = () => ({ ids: loaded, total: 65, hasMore: loaded.length < 65 });
  await assert.rejects(async () => {
    currentPage = (
      await loadListPage(6, true, snapshot, async () => {
        throw Error("offline");
      })
    ).page;
  }, /offline/);
  assert.equal(currentPage, 1);
  await assert.rejects(
    loadListPage(6, true, snapshot, async () => {}),
    /加载/
  );
  currentPage = (
    await loadListPage(6, true, snapshot, async () => {
      loaded = ids(65);
    })
  ).page;
  assert.equal(currentPage, 6);
});

function runtimeLoad(path, mocks = {}) {
  const React = require("react");
  return load(
    path,
    new Proxy(
      {
        react: {
          ...React,
          useCallback: (fn) => fn,
          useEffect() {},
          useRef: () => ({ current: null }),
          useState: (initial) => [initial, () => {}],
        },
        "mobx-react": { observer: (fn) => fn },
        "@plane/constants": { DRAG_ALLOWED_GROUPS: ["state", "priority"], ALL_ISSUES: "All Issues" },
        "@plane/types": { EIssueLayoutTypes: { LIST: "list" } },
        "@plane/utils": { cn: (value) => value },
        "@plane/i18n": { useTranslation: () => ({ t: (value) => value }) },
        "@/hooks/store/use-project-state": { useProjectState: () => ({}) },
        "@/components/workflow": {
          useWorkFlowFDragNDrop: () => ({ getIsWorkflowWorkItemCreationDisabled: () => false }),
        },
        "./pagination": paging(),
        "./use-page-size": { useListPageSize: () => ({ key: "list-test", pageSize: 10, setPageSize() {} }) },
        ...mocks,
      },
      {
        get: (target, id) =>
          id === "react/jsx-runtime" ? require(id) : (target[id] ?? new Proxy({}, { get: () => () => null })),
      }
    )
  );
}
test("各分组独立取数，未分组使用全局游标，成功后才提交页码", async () => {
  for (const groupBy of ["state", "priority", "module", "cycle", null]) {
    let loaded = ids(groupBy ? 50 : 100);
    const calls = [],
      pages = [],
      snapshots = [];
    const total = groupBy ? 65 : 125;
    const { ListGroup } = runtimeLoad("../core/components/issues/issue-layouts/list/list-group.tsx", {
      "@/hooks/use-issue-layout-store": {
        useIssuesStore: () => ({
          issues: {
            getGroupIssueCount: () => total,
            getIssueLoader: () => undefined,
            getIssueIds: (id) => {
              snapshots.push(id);
              return loaded;
            },
            getPaginationData: () => ({ nextPageResults: loaded.length < total }),
          },
        }),
      },
    });
    const tree = ListGroup({
      group: { id: groupBy ? "closed" : "All Issues", name: "测试" },
      group_by: groupBy,
      groupIssueIds: loaded,
      page: 1,
      collapsedGroups: { group_by: [] },
      selectionHelpers: { handleClearSelection() {} },
      loadMoreIssues: async (id) => {
        calls.push(id);
        assert.deepEqual(pages, []);
        loaded = ids(total);
      },
      onPageChange: (value) => pages.push(value),
    });
    const footer = tree.props.children[1].props.children[2];
    await footer.props.onPage(6);
    assert.deepEqual(calls, [groupBy ? "closed" : undefined]);
    assert.ok(snapshots.every((id) => id === (groupBy ? "closed" : undefined)));
    assert.deepEqual(pages, [6]);
  }
});
test("批量选择只包括每组当前页，各组页码互不影响", () => {
  const React = require("react");
  const { List } = runtimeLoad("../core/components/issues/issue-layouts/list/default.tsx", {
    react: {
      ...React,
      useEffect() {},
      useRef: () => ({ current: null }),
      useState: () => [
        { scope: JSON.stringify(["list-test", 10, "null", undefined]), pages: { closed: 2, open: 1 } },
        () => {},
      ],
    },
    "@/hooks/use-issue-layout-store": {
      useIssueStoreType: () => "project",
      useIssuesStore: () => ({ issues: { getGroupIssueCount: (id) => (id === "closed" ? 50 : 25) } }),
    },
    "@/hooks/use-bulk-operation-status": { useBulkOperationStatus: () => true },
    "../utils": {
      getGroupByColumns: () => [{ id: "closed" }, { id: "open" }],
      isSubGrouped: () => false,
      isWorkspaceLevel: () => false,
    },
  });
  const tree = List({ groupedIssueIds: { closed: ids(50), open: ids(25) }, group_by: "state" });
  assert.deepEqual(tree.props.children.props.entities, { closed: ids(50).slice(10, 20), open: ids(10) });
});
test("页码输入拒绝小数，上一页下一页和跳转均绑定实际页码", async () => {
  const React = require("react"),
    changes = [];
  for (const jump of ["4", "2.5"]) {
    const { ListPagination } = runtimeLoad("../core/components/issues/issue-layouts/list/pagination-controls.tsx", {
      react: { ...React, useEffect() {}, useState: () => [jump, () => {}] },
    });
    const tree = ListPagination({
      label: "测试",
      page: 2,
      pageCount: 7,
      from: 11,
      to: 20,
      total: 65,
      busy: false,
      error: false,
      onPage: async (page) => changes.push(page),
    });
    const controls = tree.props.children[4].props.children;
    if (jump === "4") {
      controls[0].props.onClick();
      controls[2].props.onClick();
    }
    controls[3].props.onSubmit({ preventDefault() {} });
  }
  assert.deepEqual(changes, [1, 3, 4]);
});

test("缓存数组原地追加也能正确判断取数进展", async () => {
  const { loadListPage } = paging();
  const loaded = ids(50);
  const page = await loadListPage(
    6,
    true,
    () => ({ ids: loaded, total: 65, hasMore: loaded.length < 65 }),
    async () => {
      loaded.push(...ids(65).slice(50));
    }
  );
  assert.deepEqual(page.visibleIds, ids(65).slice(50, 60));
});

test("列表每页条数支持10/20/50，尾页和可选值边界准确", async () => {
  const { listPageWindow, normalizeListPageSize, LIST_PAGE_SIZES } = paging();
  assert.deepEqual(LIST_PAGE_SIZES, [10, 20, 50]);
  for (const size of LIST_PAGE_SIZES) {
    const window = listPageWindow(ids(107), 107, true, 3, size);
    assert.deepEqual(window.visibleIds, ids(107).slice(size * 2, size * 3));
    assert.equal(window.pageSize, size);
  }
  assert.equal(normalizeListPageSize(999, true), 10);
  assert.equal(normalizeListPageSize(null, false), 20);
  assert.equal(normalizeListPageSize("50", true), 10);
});
test("列表持久化键隔离用户、页面、分组和其他布局", () => {
  const { listPageSizeKey } = paging();
  const key = listPageSizeKey("u1", "/w/p/issues", "project", "state");
  assert.match(key, /^list-page-size:/);
  assert.notEqual(key, listPageSizeKey("u2", "/w/p/issues", "project", "state"));
  assert.notEqual(key, listPageSizeKey("u1", "/w/p/other", "project", "state"));
  assert.notEqual(key, listPageSizeKey("u1", "/w/p/issues", "project", null));
});

test("每页控件在单页也显示10/20/50，修改值传递到列表", () => {
  const changes = [];
  const { ListPagination } = runtimeLoad("../core/components/issues/issue-layouts/list/pagination-controls.tsx");
  const tree = ListPagination({
    label: "全部",
    page: 1,
    pageCount: 1,
    from: 1,
    to: 8,
    total: 8,
    busy: false,
    error: false,
    pageSize: 20,
    onPageSizeChange: (size) => changes.push(size),
  });
  const select = tree.props.children[3].props.children[1];
  assert.equal(select.props["aria-label"], "列表每页条数");
  assert.equal(select.props.value, 20);
  assert.deepEqual(
    select.props.children.map((option) => option.props.value),
    [10, 20, 50]
  );
  select.props.onChange({ target: { value: "50" } });
  assert.deepEqual(changes, [50]);
});
test("修改每页条数重置所有分组页码并保持筛选排序，批量选择同步可见条数", () => {
  const React = require("react");
  let pageSize = 20,
    state = {
      scope: JSON.stringify(["list-test", 20, '{"priority":"high"}', "created_at"]),
      pages: { closed: 2, open: 2 },
    };
  let cleared = 0;
  const filters = { priority: "high" },
    original = JSON.stringify(filters);
  const { List } = runtimeLoad("../core/components/issues/issue-layouts/list/default.tsx", {
    react: {
      ...React,
      useEffect() {},
      useRef: () => ({ current: null }),
      useState: () => [
        state,
        (next) => {
          state = typeof next === "function" ? next(state) : next;
        },
      ],
    },
    "./use-page-size": {
      useListPageSize: () => ({
        key: "list-test",
        pageSize,
        setPageSize: (size) => {
          pageSize = size;
        },
      }),
    },
    "@/hooks/use-issue-layout-store": {
      useIssueStoreType: () => "project",
      useIssuesStore: () => ({
        issues: { getGroupIssueCount: (id) => (id === "closed" ? 100 : 60) },
        issuesFilter: { appliedFilters: filters },
      }),
    },
    "@/hooks/use-bulk-operation-status": { useBulkOperationStatus: () => true },
    "../utils": {
      getGroupByColumns: () => [{ id: "closed" }, { id: "open" }],
      isSubGrouped: () => false,
      isWorkspaceLevel: () => false,
    },
  });
  const props = { groupedIssueIds: { closed: ids(100), open: ids(60) }, group_by: "priority", orderBy: "created_at" };
  const before = List(props).props.children;
  assert.deepEqual(before.props.entities.closed, ids(100).slice(20, 40));
  const groups = before.props.children({
    handleClearSelection: () => {
      cleared++;
    },
  }).props.children[0].props.children;
  groups[0].props.onPageSizeChange(50);
  assert.equal(cleared, 1);
  const after = List(props).props.children;
  assert.equal(after.props.entities.closed.length, 50);
  assert.deepEqual(after.props.entities.closed, ids(50));
  assert.deepEqual(after.props.entities.open, ids(50));
  const newGroups = after.props.children({ handleClearSelection() {} }).props.children[0].props.children;
  assert.ok(newGroups.every((group) => group.props.page === 1 && group.props.pageSize === 50));
  assert.equal(newGroups[0].props.group_by, "priority");
  assert.equal(newGroups[0].props.orderBy, "created_at");
  assert.equal(JSON.stringify(filters), original);
});
test("每页偏好切换用户和页面会重读，禁止本地存储仍可操作", () => {
  const originalWindow = globalThis.window;
  const storage = new Map();
  let blocked = false,
    user = "u1",
    path = "/w/project/issues",
    saved,
    previousDeps,
    cleanup;
  globalThis.window = Object.assign(new EventTarget(), {
    localStorage: {
      getItem(key) {
        if (blocked) throw Error("blocked");
        return storage.get(key) ?? null;
      },
      setItem(key, value) {
        if (blocked) throw Error("blocked");
        storage.set(key, value);
      },
      removeItem(key) {
        if (blocked) throw Error("blocked");
        storage.delete(key);
      },
    },
  });
  const effects = [];
  const storageHelpers = load("../core/hooks/use-local-storage.tsx", { react: {} });
  const { useListPageSize } = load("../core/components/issues/issue-layouts/list/use-page-size.ts", {
    react: {
      useState: () => [
        saved,
        (next) => {
          saved = next;
        },
      ],
      useCallback: (fn) => fn,
      useEffect: (fn, deps) => {
        if (JSON.stringify(deps) !== JSON.stringify(previousDeps)) {
          previousDeps = deps;
          effects.push(fn);
        }
      },
    },
    "next/navigation": { usePathname: () => path },
    "@/hooks/store/user": { useUser: () => ({ data: { id: user } }) },
    "@/hooks/use-local-storage": storageHelpers,
    "./pagination": paging(),
  });
  function render(group = "state") {
    const first = useListPageSize("project", group);
    if (effects.length) {
      cleanup?.();
      cleanup = effects.shift()();
      return useListPageSize("project", group);
    }
    return first;
  }
  try {
    assert.equal(render().pageSize, 10);
    render().setPageSize(50);
    assert.equal(render().pageSize, 50);
    user = "u2";
    assert.equal(render().pageSize, 10);
    user = "u1";
    assert.equal(render().pageSize, 50);
    path = "/w/other/issues";
    assert.equal(render().pageSize, 10);
    assert.equal(render(null).pageSize, 20);
    blocked = true;
    user = "u3";
    assert.equal(render().pageSize, 10);
    assert.doesNotThrow(() => render().setPageSize(20));
    assert.equal(render().pageSize, 20);
  } finally {
    cleanup?.();
    globalThis.window = originalWindow;
  }
});

test("50条每页的远页跳转按新条数补取游标批次", async () => {
  const { loadListPage } = paging();
  let loaded = ids(50),
    calls = 0;
  const page = await loadListPage(
    3,
    true,
    () => ({ ids: loaded, total: 125, hasMore: loaded.length < 125 }),
    async () => {
      calls++;
      loaded = ids(Math.min(125, loaded.length + 50));
    },
    50
  );
  assert.equal(calls, 2);
  assert.equal(page.pageSize, 50);
  assert.equal(page.pageCount, 3);
  assert.deepEqual(page.visibleIds, ids(125).slice(100));
});

test("列表空分组快速新建不把占位符当关联字段", () => {
  const QuickAdd = () => null;
  function walk(node) {
    if (!node || typeof node !== "object") return [];
    if (Array.isArray(node)) return node.flatMap(walk);
    return [...(node.type === QuickAdd ? [node] : []), ...walk(node.props?.children)];
  }
  for (const grouping of ["cycle", "module", "labels", "assignees"]) {
    const { ListGroup } = runtimeLoad("../core/components/issues/issue-layouts/list/list-group.tsx", {
      "../quick-add": { QuickAddIssueRoot: QuickAdd },
      "@/hooks/use-issue-layout-store": {
        useIssuesStore: () => ({ issues: { getGroupIssueCount: () => 1, getIssueLoader: () => undefined } }),
      },
    });
    const tree = ListGroup({
      group: { id: "None", name: "未分配" },
      group_by: grouping,
      groupIssueIds: [],
      page: 1,
      showEmptyGroup: true,
      collapsedGroups: { group_by: [] },
      selectionHelpers: { handleClearSelection() {} },
      enableIssueQuickAdd: true,
    });
    const prefilled = walk(tree)[0].props.prePopulatedData;
    assert.deepEqual(
      Object.keys(prefilled).filter((key) => key !== "state_id"),
      [],
      grouping
    );
  }
});
