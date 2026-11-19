import { groupSuccessfulInspections } from "./timeline-groups-fixture.js";
import { ConfigurationChangeDiff } from "./configuration-diff-fixture.js";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
const nodes = (t) =>
  t?.type === ConfigurationChangeDiff
    ? nodes(ConfigurationChangeDiff(t.props))
    : !t || typeof t !== "object"
      ? []
      : Array.isArray(t)
        ? t.flatMap(nodes)
        : [t, ...nodes(t.props?.children)];
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
function primaryText(tree) {
  if (tree === null || tree === undefined || tree === false) return "";
  if (typeof tree !== "object") return String(tree);
  if (Array.isArray(tree)) return tree.map(primaryText).join("");
  if (
    tree.type === "details" &&
    [tree.props.children].flat().some((child) => child?.type === "summary" && child.props.children === "技术记录")
  )
    return "";
  return primaryText(tree.props?.children);
}

function component(
  initial,
  sourceData = data,
  defectFlow = {
    value: { id: "d" },
    context: {},
    activeTab: "overview",
    expanded: false,
    onExpandedChange() {},
    onNavigate() {},
  },
  kind = "defect"
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
    if (id === "./configuration-change-diff") return { ConfigurationChangeDiff };
    if (id === "./timeline-inspection-groups") return { groupSuccessfulInspections };
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
      return exp.RecordProgress({ base: "/q/", kind, id: "d", projectUrl: "/w/p/P/", defectFlow });
    },
  };
}
test("默认仅显示进度入口，非缺陷的阶段图保留宽弹窗", () => {
  const h = component("details", data, null, "plan");
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
test("缺陷默认不显示流程图，进度菜单选择阶段图时嵌入详情；其他视图保留弹窗", () => {
  let expandedState = false;
  const changes = [];
  const flow = {
    value: {},
    context: {},
    activeTab: "diagnosis",
    get expanded() {
      return expandedState;
    },
    onExpandedChange(value) {
      expandedState = value;
      changes.push(value);
    },
    onNavigate() {},
  };
  const h = component("details", data, flow);
  assert.equal(nodes(h.render()).filter((n) => n.type === Flow).length, 0);
  nodes(h.render())
    .find((n) => n.type === Item && n.key === "stages")
    .props.onClick();
  assert.equal(expandedState, true);
  assert.ok(h.requests.every((request) => request === null || !String(request).includes("record-progress")));
  const expanded = component("details", data, { ...flow, expanded: true }).render();
  assert.equal(nodes(expanded).filter((n) => n.type === Flow).length, 1);
  assert.equal(
    nodes(expanded).some((n) => n.type === Modal),
    false
  );
  nodes(expanded)
    .find((n) => n.type === Item && n.key === "stages")
    .props.onClick();
  assert.equal(expandedState, false);
  assert.deepEqual(changes, [true, false]);
  const timeline = component("details", data, flow);
  nodes(timeline.render())
    .find((n) => n.type === Item && n.key === "timeline")
    .props.onClick();
  assert.ok(nodes(timeline.render()).some((n) => n.type === Modal));
  const plan = component("details", data, null, "plan");
  nodes(plan.render())
    .find((n) => n.type === Item && n.key === "stages")
    .props.onClick();
  assert.equal(nodes(plan.render()).filter((n) => n.props?.["data-stage"]).length, 4);
  assert.ok(nodes(plan.render()).some((n) => n.type === Modal));
});
test("非缺陷对象的阶段图仍使用原来的服务端阶段数据", () => {
  const tree = component("stages", data, null, "plan").render();
  const modal = nodes(tree).find((n) => n.type === Modal);
  assert.ok(modal);
  assert.equal(nodes(modal).filter((n) => n.type === Flow).length, 0);
  assert.equal(nodes(modal).filter((n) => n.props?.["data-stage"]).length, 4);
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

test("缺陷内嵌阶段图使用API事实并可折叠回详情", () => {
  const completed = {
    ...data,
    current: "resolved",
    stages: [
      { key: "open", name: "待处理", state: "completed" },
      { key: "in_progress", name: "处理中", state: "pending" },
      { key: "resolved", name: "待回归", state: "current" },
    ],
  };
  const flow = {
    value: { id: "d" },
    context: {},
    activeTab: "regression",
    expanded: true,
    onExpandedChange() {},
    onNavigate() {},
  };
  const h = component("details", completed, flow);
  let tree = h.render();
  assert.equal(nodes(tree).filter((n) => n.type === Flow).length, 1);
  assert.ok(!nodes(tree).some((n) => n.type === Modal));
  assert.equal(nodes(tree).filter((n) => n.type === Flow).length, 1);
  assert.ok(h.requests.every((request) => request === null || !String(request).includes("record-progress")));
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
  const tree = component("stages", closed, null, "plan").render();
  assert.equal(nodes(tree).filter((n) => n.props?.["data-state"] === "skipped").length, 1);
});

test("处理历程正文使用精确去编号的任务摘要，原记录和配置差异保留折叠详情", () => {
  const raw = "Agent 配置修复：任务 95f89e89-3d92-4f6c-a6aa-9b95fddfcd88";
  const source = {
    ...data,
    events: [
      {
        id: "remote",
        label: "Agent 配置修复",
        actor: "技术员",
        date: "2026-11-19T10:00:00Z",
        note: "BASEKNOW-D-477 第1轮诊断修复 · 配置修改：完成",
        details: raw,
        remote_process: {
          summary: "BASEKNOW-D-477 第1轮诊断修复 · 配置修改：完成",
          defect_code: "BASEKNOW-D-477",
          round: 1,
          target: { label: "机器人", username: "robot", host: "10.0.0.177" },
          command: {
            argv: ["inspect", "config.json"],
            path: "/home/robot/config.json",
            exit_code: 0,
            changes: [
              {
                key: "robot_port",
                before: 18778,
                after: 18777,
                before_exists: true,
                after_exists: true,
                line: 42,
                path: "/home/robot/config.json",
              },
            ],
          },
          run_id: "95f89e89-3d92-4f6c-a6aa-9b95fddfcd88",
        },
      },
    ],
  };
  const tree = component("timeline", source).render();
  const row = nodes(tree).find((node) => node.type === "li");
  const visible = [row.props.children].flat().filter((node) => node?.type !== "details");
  assert.match(JSON.stringify(visible), /第1轮诊断修复 · 配置修改：完成/);
  assert.doesNotMatch(JSON.stringify(visible), /BASEKNOW-D-477|95f89e89/);
  const details = nodes(row).find((node) => node.type === "details");
  assert.equal(details.props.open, undefined);
  for (const text of [
    raw,
    "BASEKNOW-D-477",
    "robot",
    "10.0.0.177",
    "robot_port",
    '"robot_port": 18778',
    '"robot_port": 18777',
    "config.json",
    "第42行",
  ])
    assert.ok(
      nodes(details)
        .flatMap((node) => [node.props?.children].flat())
        .filter((value) => typeof value === "string")
        .join("")
        .includes(text),
      text
    );
});

test("旧处理历程没有元数据的UUID说明默认收起但完整原文仍可查", () => {
  const raw = "人工改派：95f89e89-3d92-4f6c-a6aa-9b95fddfcd88";
  const tree = component("timeline", {
    ...data,
    events: [{ id: "old", label: "人工改派", actor: "成员", date: "2026-11-19T10:00:00Z", note: raw }],
  }).render();
  const row = nodes(tree).find((node) => node.type === "li");
  const details = nodes(row).find((node) => node.type === "details");
  assert.ok(details);
  assert.equal(details.props.open, undefined);
  assert.match(JSON.stringify(details), /95f89e89/);
});

test("处理历程只读校验使用文件校验值并把编号原文放二级技术记录", () => {
  const note = "Agent 读取配置：工具执行完成；任务 95f89e89-3d92-4f6c-a6aa-9b95fddfcd88";
  const process = {
    summary: "BASEKNOW-D-481 第1轮只读诊断 · 读取配置：完成",
    defect_code: "BASEKNOW-D-481",
    round: 1,
    command: { kind: "read_file", path: "/home/robot/config.json", sha256: "a".repeat(64) },
    run_id: "95f89e89-3d92-4f6c-a6aa-9b95fddfcd88",
  };
  const tree = component("timeline", {
    ...data,
    events: [
      {
        id: "read",
        label: "读取配置",
        actor: "成员",
        date: "2026-11-19T10:00:00Z",
        note: process.summary,
        details: note,
        remote_process: process,
      },
    ],
  }).render();
  const row = nodes(tree).find((node) => node.type === "li");
  const details = nodes(row).find((node) => node.type === "details");
  const technical = nodes(details).find(
    (node) =>
      node.type === "details" &&
      [node.props.children].flat().some((child) => child?.type === "summary" && child.props.children === "技术记录")
  );
  assert.ok(technical);
  assert.equal(technical.props.open, undefined);
  const primary = primaryText(details);
  assert.match(primary, /第1轮只读诊断/);
  assert.match(primary, /文件校验值/);
  assert.doesNotMatch(primary, /修改后|BASEKNOW-D-481|95f89e89/);
  assert.match(JSON.stringify(technical), /BASEKNOW-D-481/);
});

const inspectionEvent = (id, stage) => ({
  id,
  label: "现场检查",
  actor: "成员",
  date: "2026-11-19T10:00:00Z",
  note: id,
  remote_process: { summary: id, stage, run_id: "same-run", command: { status: "done", ok: true, exit_code: 0 } },
});

test("处理历程只折叠连续且已明确成功的同轮检查，不隐藏复测", () => {
  const tree = component("timeline", {
    ...data,
    events: [
      inspectionEvent("read-one", "inspect"),
      inspectionEvent("read-two", "inspect"),
      inspectionEvent("verify", "verify"),
    ],
  }).render();
  const group = nodes(tree).find(
    (node) =>
      node.type === "details" &&
      [node.props.children]
        .flat()
        .some((child) => child?.type === "summary" && JSON.stringify(child.props.children).includes("检查过程"))
  );
  assert.ok(group);
  assert.equal(group.props.open, undefined);
  assert.match(JSON.stringify(group), /read-one/);
  assert.match(JSON.stringify(group), /read-two/);
  assert.doesNotMatch(JSON.stringify(group), /"children":"verify"/);
});

test("处理历程读取的长校验值默认折叠，正常退出码与工具套话进入技术记录", () => {
  const process = {
    summary: "读取配置完成",
    command: { kind: "read_file", path: "/config.json", sha256: "a".repeat(64), exit_code: 0 },
    details: "读取配置文件",
  };
  const tree = component("timeline", {
    ...data,
    events: [{ id: "read", label: "读取配置", actor: "成员", date: "2026-11-19T10:00:00Z", remote_process: process }],
  }).render();
  const checks = nodes(tree).find(
    (node) =>
      node.type === "details" &&
      [node.props.children].flat().some((child) => child?.type === "summary" && child.props.children === "技术记录")
  );
  assert.ok(checks);
  assert.equal(checks.props.open, undefined);
  const technical = nodes(tree).find(
    (node) =>
      node.type === "details" &&
      [node.props.children].flat().some((child) => child?.type === "summary" && child.props.children === "技术记录")
  );
  assert.match(JSON.stringify(technical), /读取配置文件/);
});
