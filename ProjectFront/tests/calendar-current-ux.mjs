import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const Control = () => null;
Control.Button = Control;
Control.Panel = Control;
const Menu = () => null;
Menu.MenuItem = () => null;
const Header = () => null,
  Week = () => null,
  WeekHeader = () => null;
const base = "../core/components/issues/issue-layouts/calendar/";
const cn = (...args) =>
  args.flatMap((arg) => (typeof arg === "string" ? arg : Object.keys(arg || {}).filter((key) => arg[key]))).join(" ");
function load(path, mocks = {}, DateClass = Date) {
  const exports = {};
  const code = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  new Function("require", "exports", "Date", code)(
    (id) => mocks[id] ?? (id === "react/jsx-runtime" ? require(id) : new Proxy({}, { get: () => () => null })),
    exports,
    DateClass
  );
  return exports;
}
function nodes(tree) {
  if (!tree || typeof tree !== "object") return [];
  return [tree, ...React.Children.toArray(tree.props?.children).flatMap(nodes)];
}
const reactHooks = {
  ...React,
  default: React,
  useState: (value) => [value, () => {}],
  useRef: () => ({ current: null }),
  useEffect() {},
};
const basic = {
  react: reactHooks,
  "mobx-react": { observer: (fn) => fn },
  "@plane/utils": {
    cn,
    renderFormattedDate: () => "date",
    renderFormattedPayloadDate: (date) =>
      `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`,
  },
  "@plane/i18n": { useTranslation: () => ({ t: (key) => key }) },
  "next/navigation": { useParams: () => ({ projectId: "project" }) },
};
function filter(layout = "month", weekends = false) {
  return { issueFilters: { displayFilters: { calendar: { layout, show_weekends: weekends } } } };
}
test("日历菜单按月、按周和周六周日名称清晰，切换保留布局设置", () => {
  const { CALENDAR_LAYOUTS } = load("../../packages/constants/src/calendar.ts", {
    "@plane/types": { EStartOfTheWeek: {} },
  });
  const updates = [];
  const { CalendarOptionsDropdown } = load(base + "dropdowns/options-dropdown.tsx", {
    ...basic,
    "@headlessui/react": { Popover: Control, Transition: Control },
    "react-popper": { usePopper: () => ({ styles: {}, attributes: {} }) },
    "@plane/constants": { CALENDAR_LAYOUTS, EIssueFilterType: { DISPLAY_FILTERS: "display" } },
    "@/hooks/store/use-calendar-view": { useCalendarView: () => ({}) },
    "@/hooks/use-window-size": { default: () => [1200] },
  });
  const tree = CalendarOptionsDropdown({ issuesFilterStore: filter(), updateFilters: (...args) => updates.push(args) });
  const rendered = tree.props.children({ open: true, close() {} });
  const buttons = nodes(rendered).filter((node) => node.type === "button");
  const texts = buttons.map((node) =>
    React.Children.toArray(node.props.children)
      .filter((item) => typeof item === "string")
      .join("")
  );
  assert.deepEqual(texts.slice(-3), ["按月查看", "按周查看", "显示周六、周日"]);
  buttons.at(-1).props.onClick();
  assert.equal(updates[0][2].calendar.show_weekends, true);
  assert.equal(updates[0][2].calendar.layout, "month");
  let cleared = false;
  const revealed = CalendarOptionsDropdown({
    issuesFilterStore: filter(),
    showWeekends: true,
    onWeekendsChange: () => {
      cleared = true;
    },
    updateFilters: (...args) => updates.push(args),
  }).props.children({ open: true, close() {} });
  nodes(revealed)
    .find((node) => node.type === "button" && React.Children.toArray(node.props.children).includes("显示周六、周日"))
    .props.onClick();
  assert.equal(cleared, true);
  assert.equal(updates[1][2].calendar.show_weekends, false);
});
test("周末背景覆盖整个日期格，今天整格可辨识并保留内部有界滚动", () => {
  const { CalendarDayTile } = load(base + "day-tile.tsx", basic);
  const today = new Date();
  const props = {
    issuesFilterStore: filter(),
    date: { date: new Date(2026, 10, 8), is_current_month: true },
    selectedDate: today,
    groupedIssueIds: {},
    getGroupIssueCount: () => 0,
  };
  const weekend = nodes(CalendarDayTile(props)).find((node) => node.props["data-calendar-date"]);
  assert.match(weekend.props.className, /bg-layer-1/);
  const current = nodes(CalendarDayTile({ ...props, date: { date: today, is_current_month: true } })).find(
    (node) => node.props["data-calendar-date"]
  );
  assert.equal(current.props["aria-current"], "date");
  assert.match(current.props.className, /ring-2/);
  assert(nodes(current).some((node) => /pointer-events-none absolute inset-0/.test(node.props.className || "")));
  assert(nodes(CalendarDayTile(props)).some((node) => /max-h-56/.test(node.props.className || "")));
});
test("添加工作项入口始终可见，新增和关联已有工作项动作保留", () => {
  const { CalendarQuickAddIssueActions } = load(base + "quick-add-issue-actions.tsx", {
    ...basic,
    "@plane/ui": { CustomMenu: Menu },
    "@plane/types": { EIssueLayoutTypes: { CALENDAR: "calendar" } },
    "@/hooks/store/use-issue-detail": { useIssueDetail: () => ({ updateIssue() {} }) },
  });
  const quickAdd = nodes(CalendarQuickAddIssueActions({})).find((node) => node.props.customQuickAddButton);
  const button = quickAdd.props.customQuickAddButton;
  assert.doesNotMatch(button.props.className, /opacity-0/);
  assert.equal(nodes(button).filter((node) => node.type === Menu.MenuItem).length, 2);
});
test("今天按钮同时返回当前月和周并请求日期定位", () => {
  let selected, located, updated;
  const today = new Date(2026, 10, 8);
  class ClockDate extends Date {
    constructor(...args) {
      super(...(args.length ? args : [today]));
    }
  }
  const { CalendarHeader } = load(
    base + "header.tsx",
    {
      ...basic,
      "@/hooks/store/use-calendar-view": {
        useCalendarView: () => ({
          calendarFilters: { activeMonthDate: new Date(2025, 0, 1), activeWeekDate: new Date(2025, 0, 1) },
          updateCalendarFilters: (value) => (updated = value),
        }),
      },
    },
    ClockDate
  );
  const header = CalendarHeader({
    issuesFilterStore: filter(),
    setSelectedDate: (value) => (selected = value),
    onToday: (value) => (located = value),
  });
  nodes(header)
    .find((node) => node.type === "button" && node.props.children === "common.today")
    .props.onClick();
  assert.equal(updated.activeMonthDate.getTime(), new Date(2026, 10, 1).getTime());
  assert.equal(updated.activeWeekDate.getTime(), today.getTime());
  assert.equal(selected.getTime(), today.getTime());
  assert.equal(located?.getTime(), today.getTime());
});
test("日期重新渲染后才滚动聚焦今天，隐藏周末时同步展示周末列并播报选中日期", () => {
  const slots = [],
    effects = [];
  let index = 0,
    scrolled = 0,
    focused = 0;
  const target = {
    scrollIntoView: (value) => {
      assert.equal(value.block, "center");
      scrolled++;
    },
    focus: () => focused++,
  };
  const root = {
    querySelector: (selector) => {
      assert.equal(selector, '[data-calendar-date="2026-11-08"]');
      return target;
    },
  };
  const hooks = {
    ...React,
    useState: (initial) => {
      const key = index++;
      if (!(key in slots)) slots[key] = initial;
      return [slots[key], (value) => (slots[key] = value)];
    },
    useRef: (initial) => {
      const key = index++;
      if (!(key in slots)) slots[key] = { current: key === 3 ? root : initial };
      return slots[key];
    },
    useEffect: (fn) => effects.push(fn),
  };
  const { CalendarChart } = load(base + "calendar.tsx", {
    ...basic,
    react: hooks,
    "./header": { CalendarHeader: Header },
    "./week-days": { CalendarWeekDays: Week },
    "./week-header": { CalendarWeekHeader: WeekHeader },
    "@plane/types": { EIssuesStoreType: {}, EIssueLayoutTypes: {} },
    "@/hooks/store/use-issues": { useIssues: () => ({ issues: { viewFlags: {} } }) },
    "@/hooks/use-window-size": { default: () => [1200] },
  });
  const props = {
    issuesFilterStore: filter(),
    layout: "month",
    showWeekends: false,
    groupedIssueIds: {},
    issueCalendarView: { calendarPayload: {}, allWeeksOfActiveMonth: { week: {} }, calendarFilters: {} },
  };
  const render = () => {
    index = 0;
    effects.length = 0;
    return CalendarChart(props);
  };
  let tree = render();
  nodes(tree)
    .find((node) => node.type === Header)
    .props.onToday(new Date(2026, 10, 8));
  assert.equal(scrolled, 0);
  tree = render();
  effects.forEach((fn) => fn());
  assert.equal(scrolled, 1);
  assert.equal(focused, 1);
  assert.equal(nodes(tree).find((node) => node.type === Week).props.showWeekends, true);
  assert.equal(nodes(tree).find((node) => node.type === WeekHeader).props.showWeekends, true);
  assert.equal(
    nodes(tree).find((node) => node.props["aria-live"] === "polite").props.children,
    "已定位到今天：2026/11/08"
  );
  props.layout = "week";
  tree = render();
  effects.forEach((fn) => fn());
  assert.equal(scrolled, 1, "普通切换布局不重复夺取焦点");
  nodes(tree)
    .find((node) => node.type === Header)
    .props.onToday(new Date(2026, 10, 8));
  tree = render();
  effects.forEach((fn) => fn());
  assert.equal(scrolled, 2, "周布局重复点击今天仍重新定位");
  assert.equal(nodes(tree).find((node) => node.type === Week).props.showWeekends, true);
  nodes(tree)
    .find((node) => node.type === Header)
    .props.onWeekendsChange();
  tree = render();
  assert.equal(nodes(tree).find((node) => node.type === Week).props.showWeekends, false);
});
