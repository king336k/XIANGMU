import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
const nodes = (t) =>
  !t || typeof t !== "object" ? [] : Array.isArray(t) ? t.flatMap(nodes) : [t, ...nodes(t.props?.children)];
const Menu = () => null,
  Item = () => null,
  Modal = () => null,
  Badge = () => null,
  Paging = () => null,
  Link = () => null;
Menu.MenuItem = Item;
const Flow = () => "FLOW";
const data = {
  current: "open",
  stages: [
    { key: "open", name: "待处理", state: "current" },
    { key: "in_progress", name: "处理中", state: "pending" },
    { key: "resolved", name: "待回归", state: "pending" },
    { key: "closed", name: "已关闭", state: "pending" },
  ],
  events: [
    { id: "old", label: "提交缺陷", actor: "采集员", date: "2026-11-11T09:00:00Z", note: "现场异常" },
    { id: "new", label: "退回修复", actor: "项目经理", date: "2026-11-12T10:00:00Z", note: "仍可复现", tone: "failed" },
  ],
  event_pagination: { count: 2, page: 1, per_page: 50 },
  dates: [],
  schedule: [],
  versions: [
    {
      id: "v one&2",
      version: "v2",
      name: "版本二",
      milestones: [{ id: "m", name: "发布确认", date: "2026-11-30", status: "blocked" }],
    },
  ],
};
function component(
  initial,
  sourceData = data,
  defectFlow = { value: { id: "d" }, context: {}, activeTab: "overview", onNavigate() {} }
) {
  const states = [],
    requests = [],
    exp = {};
  let index = 0;
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/quality/record-progress.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }
    ).outputText
  )((id) => {
    if (id === "react/jsx-runtime") return require(id);
    if (id === "lodash-es") return { sortBy: (rows, key) => rows.toSorted((a, b) => key(a) - key(b)) };
    if (id === "react")
      return {
        useState: (v) => {
          const at = index++;
          if (!(at in states)) states[at] = at === 0 ? initial : v;
          return [states[at], (next) => (states[at] = next)];
        },
      };
    if (id === "swr")
      return {
        default: (key) => {
          requests.push(key);
          return key ? { data: sourceData } : {};
        },
      };
    if (id === "@plane/ui") return { CustomMenu: Menu };
    if (id === "./shared") return { Modal, Badge, Paging };
    if (id === "@plane/utils") return { renderNumericDateTime: String };
    if (id === "@/components/common/project-route-link") return { ProjectRouteLink: Link };
    if (id === "./use-collection-pagination")
      return { useCollectionPagination: () => ({ query: "page=1", paging: {} }) };
    if (id === "./defect-flow-guidance") return { DefectFlowGuidance: Flow };
    return new Proxy({}, { get: () => () => null });
  }, exp);
  return {
    requests,
    render() {
      index = 0;
      return exp.RecordProgress({ base: "/q/", kind: "defect", id: "d", projectUrl: "/w/p/P/", defectFlow });
    },
  };
}
test("默认仅进度入口，四视图在宽弹窗切换且不挤压标题", () => {
  const h = component("details");
  let tree = h.render();
  assert.ok(!nodes(tree).some((n) => n.type === Modal));
  assert.equal(h.requests[0], null);
  const menu = nodes(tree).filter((n) => n.type === Item);
  assert.equal(menu.length, 4);
  menu.find((n) => n.key === "stages").props.onClick();
  tree = h.render();
  const modal = nodes(tree).find((n) => n.type === Modal);
  assert.equal(modal.props.width, "wide");
  assert.equal(nodes(modal).filter((n) => n.type === "button" && n.props["aria-current"] === "page").length, 1);
});
test("缺陷阶段图仅在进度与历程弹窗中显示", () => {
  const h = component("details", data, { value: {}, context: {}, activeTab: "diagnosis", onNavigate() {} });
  assert.equal(nodes(h.render()).filter((n) => n.type === Flow).length, 0);
  nodes(h.render())
    .find((n) => n.type === Item && n.key === "stages")
    .props.onClick();
  const modal = nodes(h.render()).find((n) => n.type === Modal);
  assert.equal(nodes(modal).filter((n) => n.type === Flow).length, 1);
});
test("阶段仅根据服务端本轮state显示已完成，重开后未到达不冒充完成", () => {
  const tree = component("stages").render();
  const modal = nodes(tree).find((n) => n.type === Modal);
  assert.ok(modal);
  assert.equal(nodes(modal).filter((n) => n.type === Flow).length, 1);
  assert.equal(nodes(modal).filter((n) => n.props?.["data-stage"]).length, 0);
});
test("处理历程按真实日期分组不重复编号，历史折叠最新展开，保留具体动作", () => {
  const tree = component("timeline").render();
  const groups = nodes(tree).filter((n) => n.type === "details" && typeof n.props.open === "boolean");
  assert.equal(groups.length, 2);
  assert.equal(groups[0].props.open, false);
  assert.equal(groups[1].props.open, true);
  assert.ok(nodes(tree).some((n) => n.type === "ul" && n.props.className.includes("list-none")));
  assert.ok(nodes(tree).some((n) => n.type === Badge && n.props.label === "退回修复" && n.props.value === "failed"));
});
test("关联里程碑编码真实版本id，保留计划日期与阻塞状态", () => {
  const tree = component("milestones").render();
  const link = nodes(tree).find((n) => n.type === Link);
  const url = new URL(link.props.to, "https://test");
  assert.equal(url.pathname, "/w/p/P/versions/");
  assert.equal(url.searchParams.get("version"), "v one&2");
  assert.equal(url.searchParams.get("display"), "milestones");
  assert.ok(nodes(tree).some((n) => n.type === Badge && n.props.value === "blocked"));
});
test("时间轴不把无效日期绘制为NaN，也不把单日期当虚构起止计划", () => {
  const exp = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/quality/schedule-timeline.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
    ).outputText
  )(
    (id) =>
      id === "react/jsx-runtime"
        ? require(id)
        : id === "./shared"
          ? { Badge }
          : id === "@/components/common/project-route-link"
            ? { ProjectRouteLink: Link }
            : new Proxy({}, { get: () => () => null }),
    exp
  );
  const tree = exp.ScheduleTimeline({
    projectUrl: "/w/p/P/",
    rows: [
      { id: "bad", name: "日期异常", start: "bad", target: "2026-11-12", status: "open", path: "issues/i/" },
      {
        id: "waiting",
        name: "未开始任务",
        start: "2026-11-12",
        target: "2026-11-14",
        status: "unstarted",
        path: "issues/w/",
      },
      {
        id: "blocked",
        name: "阻塞任务",
        start: "2026-11-12",
        target: "2026-11-14",
        status: "blocked",
        path: "issues/b/",
      },
      {
        id: "ready",
        name: "待发布版本",
        start: "2026-11-12",
        target: "2026-11-14",
        status: "ready",
        path: "versions/v/",
      },
      {
        id: "point",
        name: "单目标",
        start: null,
        target: "2026-11-15",
        status: "completed",
        path: "versions?version=v&display=timeline",
      },
    ],
  });
  assert.doesNotMatch(JSON.stringify(tree), /NaN|null%/);
  assert.ok(nodes(tree).some((n) => n.props?.["data-date-kind"] === "point"));
  assert.ok(nodes(tree).some((n) => n.props?.children === "日期待核对"));
  const barFor = (id) =>
    nodes(nodes(tree).find((n) => n.type === Link && n.key === id)).find((n) => n.props?.["data-date-kind"]);
  assert.match(barFor("blocked").props.className, /bg-danger-primary/);
  assert.match(barFor("ready").props.className, /bg-warning-primary/);
  assert.match(barFor("waiting").props.className, /border-strong/);
  assert.match(barFor("waiting").props.className, /bg-layer-1/);
});

test("已完成阶段只使用API事实，关闭弹窗回原页面而不触发导航", () => {
  const completed = {
    ...data,
    current: "resolved",
    stages: [
      { key: "open", name: "待处理", state: "completed" },
      { key: "in_progress", name: "处理中", state: "pending" },
      { key: "resolved", name: "待回归", state: "current" },
    ],
  };
  const h = component("stages", completed);
  let tree = h.render();
  assert.equal(nodes(tree).filter((n) => n.type === Flow).length, 1);
  nodes(tree)
    .find((n) => n.type === Modal)
    .props.onClose();
  tree = h.render();
  assert.ok(!nodes(tree).some((n) => n.type === Modal));
  assert.equal(h.requests.at(-1), null);
});

test("缺少独立状态记录时明确提示未单独记录，不冒充完成", () => {
  const closed = {
    ...data,
    current: "closed",
    stages: data.stages.map((s) => ({
      key: s.key,
      name: s.name,
      state: s.key === "closed" ? "current" : s.key === "in_progress" ? "skipped" : "completed",
    })),
  };
  const tree = component("stages", closed).render();
  assert.equal(nodes(tree).filter((n) => n.type === Flow).length, 1);
});
