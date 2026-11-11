import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
function load(path, mocks) {
  const exports = {};
  const code = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  new Function("require", "exports", code)((id) => {
    if (mocks[id]) return mocks[id];
    if (id === "react/jsx-runtime") return require(id);
    return new Proxy({}, { get: () => () => null });
  }, exports);
  return exports;
}
test("分组列表只渲染当前页，显式翻页只请求当前分组", async () => {
  const loads = [],
    pages = [];
  let callback,
    loaded = Array.from({ length: 50 }, (_, i) => `issue-${i}`);
  const { ListGroup } = load("../core/components/issues/issue-layouts/list/list-group.tsx", {
    react: {
      ...React,
      useCallback: (fn) => fn,
      useEffect() {},
      useRef: () => ({ current: null }),
      useState: (value) => [value, () => {}],
    },
    "./pagination": load("../core/components/issues/issue-layouts/list/pagination.ts", {
      "../kanban/arrangement": load("../core/components/issues/issue-layouts/kanban/arrangement.ts", {}),
    }),
    "mobx-react": { observer: (fn) => fn },
    "@plane/constants": { DRAG_ALLOWED_GROUPS: ["state"] },
    "@plane/types": { EIssueLayoutTypes: { LIST: "list" } },
    "@plane/utils": { cn: (x) => x },
    "@plane/i18n": { useTranslation: () => ({ t: (key) => key }) },
    "@/hooks/use-intersection-observer": {
      useIntersectionObserver: (_root, _target, fn) => {
        callback = fn;
      },
    },
    "@/hooks/store/use-project-state": { useProjectState: () => ({}) },
    "@/hooks/use-issue-layout-store": {
      useIssuesStore: () => ({
        issues: {
          getGroupIssueCount: () => 55,
          getPaginationData: () => ({ nextPageResults: loaded.length < 55 }),
          getIssueLoader: () => undefined,
          getIssueIds: () => loaded,
        },
      }),
    },
    "@/components/workflow": { useWorkFlowFDragNDrop: () => ({ getIsWorkflowWorkItemCreationDisabled: () => false }) },
  });
  const tree = ListGroup({
    group: { id: "closed", name: "已完成" },
    groupIssueIds: loaded,
    group_by: "state",
    page: 1,
    onPageChange: (page) => pages.push(page),
    selectionHelpers: { handleClearSelection() {} },
    loadMoreIssues: async (id) => {
      loads.push(id);
      loaded = Array.from({ length: 55 }, (_, i) => `issue-${i}`);
    },
    collapsedGroups: { group_by: [] },
  });
  assert.equal(callback, undefined);
  assert.deepEqual(loads, []);
  const body = tree.props.children[1].props.children;
  assert.equal(body[1].props.issueIds.length, 10);
  await body[2].props.onPage(6);
  assert.deepEqual(loads, ["closed"]);
  assert.deepEqual(pages, [6]);
});
test("右上角显示菜单仅在普通看板提供排列设置，其他布局和泳道不误用", () => {
  const Control = () => null;
  const { DisplayFiltersSelection } = load(
    "../core/components/issues/issue-layouts/filters/header/display-filters/display-filters-selection.tsx",
    {
      react: React,
      "mobx-react": { observer: (fn) => fn },
      "lodash-es": { isEmpty: () => true },
      "@/components/issues/issue-layouts/kanban/arrangement-control": { KanbanArrangementControl: Control },
    }
  );
  for (const layout of ["list", "kanban", "calendar", "spreadsheet", "gantt_chart"]) {
    const tree = DisplayFiltersSelection({
      displayFilters: { layout, group_by: "state" },
      displayProperties: {},
      layoutDisplayFiltersOptions: { extra_options: { access: false } },
    });
    assert.equal(tree.props.children[0]?.type === Control, layout === "kanban");
  }
  const swimlane = DisplayFiltersSelection({
    displayFilters: { layout: "kanban", group_by: "state", sub_group_by: "priority" },
    displayProperties: {},
    layoutDisplayFiltersOptions: { extra_options: { access: false } },
  });
  assert.equal(swimlane.props.children[0], false);
});

test("五种布局按钮提供中文可访问名称、选中状态，重复点击当前布局不重置视图", () => {
  const layouts = ["list", "kanban", "calendar", "spreadsheet", "gantt_chart"],
    changed = [];
  const { LayoutSelection } = load("../core/components/issues/issue-layouts/filters/header/layout-selection.tsx", {
    "@plane/constants": { ISSUE_LAYOUTS: layouts.map((key) => ({ key, i18n_title: key, i18n_label: key })) },
    "@plane/i18n": {
      useTranslation: () => ({
        t: (key) =>
          ({ list: "列表", kanban: "看板", calendar: "日历", spreadsheet: "表格", gantt_chart: "时间线" })[key],
      }),
    },
    "@/hooks/use-platform-os": { usePlatformOS: () => ({ isMobile: false }) },
    "@plane/utils": { cn: () => "" },
  });
  const tree = LayoutSelection({ layouts, onChange: (value) => changed.push(value), selectedLayout: "kanban" });
  const buttons = tree.props.children.map((node) => node.props.children);
  assert.deepEqual(
    buttons.map((button) => button.props["aria-label"]),
    ["切换为列表", "切换为看板", "切换为日历", "切换为表格", "切换为时间线"]
  );
  assert.equal(buttons[1].props["aria-pressed"], true);
  buttons[1].props.onClick();
  assert.deepEqual(changed, []);
  buttons[0].props.onClick();
  assert.deepEqual(changed, ["list"]);
});

test("时间线区分已加载数量和总数，避免100条分页被误当总数", () => {
  const { GanttChartHeader } = load("../core/components/gantt-chart/chart/header.tsx", {
    "mobx-react": { observer: (fn) => fn },
    "@plane/i18n": { useTranslation: () => ({ t: (key) => key }) },
    "@/hooks/use-timeline-chart": { useTimeLineChartStore: () => ({ currentView: "week" }) },
    "@/components/gantt-chart/data": { VIEWS_LIST: [] },
  });
  const header = GanttChartHeader({
    blockIds: Array(100).fill("id"),
    totalBlockCount: 275,
    loaderTitle: "工作项",
    showToday: false,
  });
  assert.equal(header.props.children[0].props.children.props.children, "100/275 工作项");
});
test("日历月份使用数字年月，周标题使用数字日期范围", () => {
  const Control = () => null;
  Control.Button = Control;
  Control.Panel = Control;
  const { CalendarMonthsDropdown } = load(
    "../core/components/issues/issue-layouts/calendar/dropdowns/months-dropdown.tsx",
    {
      react: { ...React, default: React, useState: (value) => [value, () => {}] },
      "mobx-react": { observer: (fn) => fn },
      "react-popper": { usePopper: () => ({ styles: {}, attributes: {} }) },
      "@headlessui/react": { Popover: Control, Transition: Control },
      "@plane/constants": { MONTHS_LIST: {} },
      "@plane/utils": {
        getDate: (value) => new Date(value),
        renderFormattedDate: (value) =>
          `${value.getFullYear()}/${String(value.getMonth() + 1).padStart(2, "0")}/${String(value.getDate()).padStart(2, "0")}`,
      },
      "@/hooks/store/use-calendar-view": {
        useCalendarView: () => ({
          calendarFilters: { activeMonthDate: new Date(2026, 10, 1) },
          allDaysOfActiveWeek: { "2026-11-02": {}, "2026-11-08": {} },
        }),
      },
    }
  );
  function label(layout) {
    return CalendarMonthsDropdown({ issuesFilterStore: { issueFilters: { displayFilters: { calendar: { layout } } } } })
      .props.children[0].props.children.props.children;
  }
  assert.equal(label("month"), "2026/11");
  assert.equal(label("week"), "2026/11/02 — 2026/11/08");
});
