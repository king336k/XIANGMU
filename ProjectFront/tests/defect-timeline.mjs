import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const nodes = (tree) =>
  !tree || typeof tree !== "object"
    ? []
    : Array.isArray(tree)
      ? tree.flatMap(nodes)
      : [tree, ...nodes(tree.props?.children)];
function render(events, comments, value = {}) {
  const exports = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/quality/collaboration-panel.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }
    ).outputText
  )((id) => {
    if (id === "react/jsx-runtime") return require(id);
    if (id === "react") return { useState: (v) => [v, () => {}] };
    if (id === "lodash-es") return { sortBy: (rows, key) => rows.toSorted((a, b) => key(a) - key(b)) };
    if (id === "@plane/utils") return { renderNumericDateTime: String };
    if (id === "./types")
      return {
        can: () => false,
        statusNames: { open: "待处理", in_progress: "处理中" },
        resultNames: { passed: "通过", failed: "失败", blocked: "阻塞", inconclusive: "无法判定", skipped: "跳过" },
      };
    if (id === "swr")
      return {
        default: (url) => ({
          data: url.endsWith("collaboration/") ? comments : url.endsWith("sources/") ? [] : { results: [] },
          mutate: async () => {},
        }),
      };
    return new Proxy({}, { get: (_, key) => key });
  }, exports);
  return exports.CollaborationPanel({
    base: "/q/",
    value: { id: "d", events, ...value },
    context: {},
    onChanged: async () => {},
  });
}
const events = [
  {
    id: "late",
    actor: "管理员",
    previous_status: "open",
    status: "open",
    created_at: "2026-11-12T10:00:00Z",
    note: "验证安排：复测登录路径",
  },
  {
    id: "first",
    actor: "DAQ服务",
    previous_status: "",
    status: "open",
    created_at: "2026-11-12T08:00:00Z",
    note: "采集异常上报",
  },
  {
    id: "middle",
    actor: "技术员",
    previous_status: "open",
    status: "in_progress",
    created_at: "2026-11-12T09:00:00Z",
    note: "已开始排查",
  },
];
test("缺陷时间线最早在上、最新在下，混排事件和回复且不出现编号", () => {
  const tree = render(events, [
    { id: "c", actor: "测试员", visibility: "internal", created_at: "2026-11-12T09:30:00Z", content: "已补日志" },
  ]);
  const list = nodes(tree).find((n) => n.props?.["aria-label"] === "处理时间线");
  assert.equal(list?.type, "ul");
  assert.match(list.props.className, /list-none/);
  const rows = nodes(list).filter((n) => n.type === "li");
  assert.equal(rows.length, 4);
  assert.deepEqual(
    rows.map((r) => nodes(r).find((n) => n.type === "time").props.dateTime),
    [events[1].created_at, events[2].created_at, "2026-11-12T09:30:00Z", events[0].created_at]
  );
  assert.equal(events[0].id, "late", "排序不修改API返回数组");
});
test("验证安排用具体动作替代更新记录且不重复前缀，重复真实事件保留", () => {
  const tree = render([events[0], { ...events[0], id: "late2" }], []);
  const rows = nodes(tree).filter((n) => n.type === "li");
  assert.equal(rows.length, 2);
  for (const row of rows) {
    const text = new Set(nodes(row).flatMap((n) => (typeof n.props?.children === "string" ? [n.props.children] : [])));
    assert.ok(text.has("验证安排"));
    assert.ok(text.has("复测登录路径"));
    assert.ok(!text.has("更新记录"));
    assert.ok(!text.has("验证安排：复测登录路径"));
  }
});

test("历史日期默认折叠、最近日期展开，长说明收起且不丢内容", () => {
  const long = "真实附件说明".repeat(50);
  const tree = render([events[1], { ...events[0], created_at: "2026-11-13T10:00:00Z", note: long }], []);
  const groups = nodes(tree).filter((n) => n.type === "details" && typeof n.props.open === "boolean");
  assert.equal(groups.length, 2);
  assert.equal(groups[0].props.open, false);
  assert.equal(groups[1].props.open, true);
  const content = nodes(groups[1]).find((n) => n.type === "details" && n.props.open === undefined);
  assert.equal(content.props.open, undefined);
  assert.ok(nodes(content).some((n) => n.props?.children === long));
});
test("通过和返修都有语义色且保留动作文字", () => {
  const tree = render(
    [
      { ...events[0], status: "closed", previous_status: "in_progress", note: "验证通过" },
      { ...events[0], id: "returned", note: "退回修复：仍可复现" },
    ],
    []
  );
  const spans = nodes(tree).filter((n) => n.type === "span");
  assert.ok(spans.some((n) => n.props.className?.includes("text-success-primary")));
  assert.ok(spans.some((n) => n.props.className?.includes("text-danger-primary") && n.props.children === "退回修复"));
});
test("回归动作展示结果语义色，旧空说明冒号清理但不改历史数据", () => {
  const input = [
    { ...events[0], id: "case", note: "执行用例第2轮「采集检查」：passed" },
    { ...events[0], id: "failed", note: "执行用例第2轮「遥操检查」：failed" },
    { ...events[0], id: "submit", note: "提交验证结果，验证第2轮：" },
    { ...events[0], id: "closed", note: "验收关闭，验证第2轮：" },
    { ...events[0], id: "assign", note: "指派测试员，验证第2轮：test → tester2" },
  ];
  const tree = render(input, []);
  const spans = nodes(tree).filter((node) => node.type === "span");
  assert.ok(
    spans.some((node) => node.props.children === "执行用例" && node.props.className.includes("text-success-primary"))
  );
  assert.ok(
    spans.some((node) => node.props.children === "执行用例" && node.props.className.includes("text-danger-primary"))
  );
  assert.ok(
    spans.some(
      (node) => node.props.children === "提交验证结果" && node.props.className.includes("text-warning-primary")
    )
  );
  const text = nodes(tree)
    .flatMap((node) => (typeof node.props?.children === "string" ? [node.props.children] : []))
    .join(" ");
  assert.ok(text.includes("执行用例第2轮「采集检查」：通过"));
  assert.ok(!text.includes("验证第2轮： "));
  assert.ok(text.includes("test → tester2"));
  assert.equal(input[2].note, "提交验证结果，验证第2轮：");
});

test("DAQ创建记录显示真实采集员和问题标题，不再展示服务账号和技术说明", () => {
  const event = {
    id: "created",
    actor: "DAQ反馈服务",
    previous_status: "",
    status: "open",
    created_at: "2026-11-12T07:10:00Z",
    note: "DAQ启动或采集异常，等待真实诊断材料；事件不是采集Session。",
  };
  const tree = render([event], [], {
    source_kind: "daq",
    title: "数据异常",
    reporter: { id: 228, username: "caiji2" },
  });
  const all = nodes(tree),
    texts = all
      .flatMap((n) => [n.props?.children].flat())
      .filter((v) => typeof v === "string")
      .join("");
  assert.ok(texts.includes("DAQ异常反馈上报"));
  assert.ok(texts.includes("采集员：caiji2"));
  assert.ok(texts.includes("问题：数据异常"));
  assert.ok(!texts.includes("DAQ反馈服务"));
  assert.ok(!texts.includes("事件不是采集Session"));
  const action = all.find((n) => n.props?.children === "DAQ异常反馈上报");
  assert.match(action.props.className, /text-secondary/);
});
