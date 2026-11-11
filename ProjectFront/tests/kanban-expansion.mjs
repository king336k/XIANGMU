import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
const api = {};
new Function(
  "exports",
  ts.transpileModule(
    readFileSync(new URL("../core/components/issues/issue-layouts/kanban/arrangement.ts", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }
  ).outputText
)(api);
const { boardCardWindow, normalizeBoardArrangement, boardInitialCount } = api;
test("两列先显示5条，展开保留前文并逐步增加，55条最后一批不越界", () => {
  const ids = Array.from({ length: 55 }, (_, i) => `case-${i + 1}`);
  assert.equal(boardCardWindow(ids, 55, 5, 0).visibleIds.length, 5);
  assert.equal(boardCardWindow(ids, 55, 5, 5).visibleIds.length, 10);
  assert.deepEqual(boardCardWindow(ids, 55, 5, 5).visibleIds.slice(0, 5), ids.slice(0, 5));
  assert.equal(boardCardWindow(ids, 55, 5, 50).visibleIds.length, 55);
  assert.equal(boardCardWindow(ids, 55, 5, 50).remaining, 0);
  assert.equal(boardCardWindow(ids, 55, 5, 0).remaining, 50);
});
test("展开跨过服务端批次时只请求缺少的一批，收起回到初始5条不丢记录", () => {
  const ids = Array.from({ length: 30 }, (_, i) => `${i}`);
  assert.equal(boardCardWindow(ids, 55, 5, 20).needsFetch, false);
  assert.equal(boardCardWindow(ids, 55, 5, 25).needsFetch, false);
  assert.equal(boardCardWindow(ids, 55, 5, 30).needsFetch, true);
  assert.equal(boardCardWindow(ids, 55, 5, 30).visibleIds.length, 30);
  assert.equal(boardCardWindow(ids, 55, 5, 0).visibleIds.length, 5);
  assert.equal(ids.length, 30);
});
test("横向、两列、单列分别记住初始条数，旧设置无损兼容", () => {
  const old = { layout: "two-columns", order: ["closed", "open"] };
  assert.equal(boardInitialCount(old), 5);
  assert.equal(boardInitialCount({ layout: "horizontal" }), 5);
  assert.equal(boardInitialCount({ layout: "single-column" }), 5);
  assert.equal(boardInitialCount({ ...old, initialCounts: { "two-columns": 10, horizontal: 15 } }), 10);
  assert.equal(boardInitialCount({ ...old, initialCounts: { "two-columns": 999 } }), 5);
  assert.deepEqual(
    normalizeBoardArrangement({ ...old, initialCounts: { "two-columns": 10, horizontal: 15 } }).initialCounts,
    { "two-columns": 10, horizontal: 15 }
  );
});
test("不足5条和空状态按真实数量自然展开，不用占满固定高度", () => {
  assert.deepEqual(boardCardWindow([], 0, 5, 0), { visibleIds: [], remaining: 0, needsFetch: false });
  assert.deepEqual(boardCardWindow(["a", "b"], 2, 5, 0), { visibleIds: ["a", "b"], remaining: 0, needsFetch: false });
});

function groupHarness(overrides = {}) {
  const React = require("react"),
    slots = [],
    effects = [];
  const Pager = () => null,
    QuickAdd = () => null;
  let cursor = 0,
    fetches = 0,
    fail = false;
  const ids = Array.from({ length: 55 }, (_, i) => `case-${i + 1}`),
    groups = { state: ids.slice(0, 30) },
    Blocks = () => null;
  const mocks = {
    react: {
      ...React,
      useState: (initial) => {
        const i = cursor++;
        if (!(i in slots)) slots[i] = initial;
        return [
          slots[i],
          (value) => {
            slots[i] = value;
          },
        ];
      },
      useCallback: (fn) => fn,
      useRef: () => ({ current: null }),
      useEffect: (fn) => effects.push(fn),
    },
    "mobx-react": { observer: (fn) => fn },
    "@plane/constants": { DRAG_ALLOWED_GROUPS: ["state"] },
    "@plane/types": { EIssueLayoutTypes: { KANBAN: "kanban" } },
    "@plane/i18n": { useTranslation: () => ({ t: (x) => x }) },
    "@plane/utils": { cn: (...x) => x.filter((v) => typeof v === "string").join(" ") },
    "@/hooks/store/use-project-state": { useProjectState: () => ({}) },
    "@/hooks/use-issue-layout-store": {
      useIssuesStore: () => ({
        issues: {
          getGroupIssueCount: () => 55,
          getIssueIds: () => groups.state,
          getIssueLoader: () => undefined,
          getPaginationData: () => ({ nextPageResults: groups.state.length < 55 }),
        },
      }),
    },
    "@/hooks/use-intersection-observer": { useIntersectionObserver: (_root, target) => assert.equal(target, null) },
    "@/components/workflow": { useWorkFlowFDragNDrop: () => ({ getIsWorkflowWorkItemCreationDisabled: () => false }) },
    "./blocks-list": { KanbanIssueBlocksList: Blocks },
    "../quick-add": { QuickAddIssueRoot: QuickAdd },
    "./column-pagination": { KanbanColumnPagination: Pager },
    "./arrangement": api,
  };
  const component = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/issues/issue-layouts/kanban/kanban-group.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }
    ).outputText
  )(
    (id) => mocks[id] || (id === "react/jsx-runtime" ? require(id) : new Proxy({}, { get: () => () => null })),
    component
  );
  function render() {
    cursor = 0;
    return component.KanbanGroup({
      groupId: "state",
      sub_group_id: "null",
      group_by: "state",
      groupedIssueIds: groups,
      initialVisibleCount: 5,
      loadMoreIssues: async () => {
        fetches++;
        if (fail) throw new Error("offline");
        groups.state = ids;
      },
      ...overrides,
    });
  }
  function walk(node, predicate) {
    if (!node || typeof node !== "object") return [];
    if (Array.isArray(node)) return node.flatMap((child) => walk(child, predicate));
    return [...(predicate(node) ? [node] : []), ...walk(node.props?.children, predicate)];
  }
  return {
    render,
    prefilled: () => walk(render(), (node) => node.type === QuickAdd)[0]?.props.prePopulatedData,
    visible: () => walk(render(), (node) => node.type === Blocks)[0].props.issueIds,
    pager: () => walk(render(), (node) => node.type === Pager)[0].props,
    fetches: () => fetches,
    fail: (value) => {
      fail = value;
    },
  };
}
test("每栏初始5条，展开最多10条，翻页替换当前页，收起保留起始记录", async () => {
  const group = groupHarness();
  assert.equal(group.visible().length, 5);
  await group.pager().onExpand(true);
  assert.equal(group.visible().length, 10);
  await group.pager().onPage(3);
  assert.equal(group.visible()[0], "case-21");
  assert.equal(group.fetches(), 0);
  await group.pager().onPage(4);
  assert.equal(group.visible()[0], "case-31");
  assert.equal(group.visible().length, 10);
  assert.equal(group.fetches(), 1);
  await group.pager().onExpand(false);
  assert.equal(group.visible().length, 5);
  assert.equal(group.visible()[0], "case-31");
  assert.equal(group.render().props["data-loaded-count"], 55);
});
test("分页下一批失败保留原页和记录，重试后进入正确页", async () => {
  const group = groupHarness();
  await group.pager().onPage(6);
  assert.equal(group.visible()[0], "case-26");
  group.fail(true);
  await group.pager().onPage(7);
  assert.equal(group.visible()[0], "case-26");
  assert.equal(group.pager().page, 6);
  group.fail(false);
  await group.pager().onPage(7);
  assert.equal(group.visible()[0], "case-31");
  assert.equal(group.pager().page, 7);
});

for (const grouping of ["cycle", "module"]) {
  test(`看板在未分配${grouping}栏新建不把None作为关联编号提交`, () => {
    const prefilled = groupHarness({ group_by: grouping, groupId: "None", enableQuickIssueCreate: true }).prefilled();
    assert.ok(prefilled);
    assert.equal(prefilled.cycle_id, undefined);
    assert.equal(prefilled.module_ids, undefined);
    const linked = groupHarness({ group_by: grouping, groupId: "valid-id", enableQuickIssueCreate: true }).prefilled();
    assert.deepEqual(
      grouping === "cycle" ? linked.cycle_id : linked.module_ids,
      grouping === "cycle" ? "valid-id" : ["valid-id"]
    );
  });
  test(`看板在未分配${grouping}子分组新建不写入None或null`, () => {
    for (const value of ["None", "null"]) {
      const prefilled = groupHarness({
        group_by: "state",
        groupId: "state",
        sub_group_by: grouping,
        sub_group_id: value,
        enableQuickIssueCreate: true,
      }).prefilled();
      assert.equal(prefilled.state_id, "state");
      assert.equal(prefilled.cycle_id, undefined);
      assert.equal(prefilled.module_ids, undefined);
    }
  });
}
