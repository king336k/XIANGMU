import { AgentReportText } from "./agent-report-text-fixture.js";
import { groupSuccessfulInspections } from "./timeline-groups-fixture.js";
import { ConfigurationChangeDiff } from "./configuration-diff-fixture.js";
import { CommandExecutionResult } from "./command-execution-fixture.js";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const nodes = (tree) =>
  tree?.type === CommandExecutionResult
    ? nodes(CommandExecutionResult(tree.props))
    : tree?.type === ConfigurationChangeDiff
      ? nodes(ConfigurationChangeDiff(tree.props))
      : !tree || typeof tree !== "object"
        ? []
        : Array.isArray(tree)
          ? tree.flatMap(nodes)
          : [tree, ...nodes(tree.props?.children)];
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
    if (id === "./configuration-change-diff") return { ConfigurationChangeDiff };
    if (id === "./command-execution-result") return { CommandExecutionResult };
    if (id === "./timeline-inspection-groups") return { groupSuccessfulInspections };
    if (id === "react/jsx-runtime") return require(id);
    if (id === "./agent-report-text") return { AgentReportText };
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

test("Agent操作正文展示业务摘要，真实目标命令退出码与UUID只在默认折叠详情", () => {
  const runId = "95f89e89-3d92-4f6c-a6aa-9b95fddfcd88";
  const commandId = "87fba94f-c671-4cb7-b583-68217980e131";
  const raw = `Agent 现场排查：${runId}，命令${commandId}`;
  const tree = render(
    [
      {
        ...events[0],
        note: raw,
        remote_process: {
          summary: "D475 第1轮检查机器人配置完成",
          stage: "inspect",
          defect_code: "D475",
          round: 1,
          target: { label: "机器人", username: "robot", host: "10.0.0.177" },
          command: {
            argv: ["/usr/bin/python3", "/home/robot/inspect.py", "inspect"],
            path: "/home/robot/config.json",
            exit_code: 0,
          },
          run_id: runId,
          command_id: commandId,
          details: "读取当前配置，无修改",
        },
      },
    ],
    []
  );
  const list = nodes(tree).find((node) => node.props?.["aria-label"] === "处理时间线");
  const row = nodes(list).find((node) => node.type === "li");
  const expandedBody = primaryText(row);
  assert.match(expandedBody, /第1轮检查机器人配置完成/);
  assert.ok(!expandedBody.includes("D475"));
  const details = nodes(row).find((node) => node.type === "details");
  assert.equal(details.props.open, undefined);
  for (const value of ["robot", "10.0.0.177", "inspect.py", "config.json", runId, commandId, raw])
    assert.ok(JSON.stringify(details).includes(value));
  assert.ok(nodes(details).some((node) => node.props?.children === 0));
});

test("没有元数据的旧UUID事件只收起原文而不猜名字或删除历史信息", () => {
  const note = "人工改派：旧负责人 → 95f89e89-3d92-4f6c-a6aa-9b95fddfcd88";
  const tree = render([{ ...events[0], note }], []);
  const row = nodes(tree).find((node) => node.type === "li");
  const details = nodes(row).find((node) => node.type === "details");
  assert.ok(details);
  assert.equal(details.props.open, undefined);
  assert.ok(nodes(details).some((node) => node.props?.children === note));
  const body = row.props.children.filter((node) => node?.type !== "details");
  assert.ok(!JSON.stringify(body).includes("95f89e89"));
});

test("服务器已转可读姓名的指派正文仍保留返回的原始详情", () => {
  const original = "人工改派：旧负责人 → 技术员甲 (95f89e89-3d92-4f6c-a6aa-9b95fddfcd88)";
  const tree = render([{ ...events[0], note: "人工改派：旧负责人 → 技术员甲", details: original }], []);
  const row = nodes(tree).find((node) => node.type === "li");
  const details = nodes(row).find((node) => node.type === "details");
  assert.ok(JSON.stringify(details).includes(original));
  assert.ok(nodes(row).some((node) => node.type === "p" && node.props.children === "旧负责人 → 技术员甲"));
});

test("仅移除已知缺陷编号前缀一次，技术详情保留完整任务编号且未知编号不改", () => {
  const process = {
    summary: "BASEKNOW-D-477 第1轮诊断修复 · RAI只读检查：完成",
    defect_code: "BASEKNOW-D-477",
    round: 1,
  };
  const row = nodes(render([{ ...events[0], remote_process: process }], [], { code: "BASEKNOW-D-477" })).find(
    (node) => node.type === "li"
  );
  const details = nodes(row).find((node) => node.type === "details");
  const body = row.props.children.filter((node) => node?.type !== "details");
  assert.ok(JSON.stringify(body).includes("第1轮诊断修复 · RAI只读检查：完成"));
  assert.ok(!JSON.stringify(body).includes("BASEKNOW-D-477"));
  assert.ok(JSON.stringify(details).includes("BASEKNOW-D-477"));
  const unknown = render([{ ...events[0], remote_process: { summary: "OTHER-D-99 检查完成" } }], [], {
    code: "BASEKNOW-D-477",
  });
  assert.ok(nodes(unknown).some((node) => node.type === "p" && node.props.children === "OTHER-D-99 检查完成"));
  const partial = render([{ ...events[0], remote_process: { summary: "BASEKNOW-D-4770 检查完成" } }], [], {
    code: "BASEKNOW-D-477",
  });
  assert.ok(nodes(partial).some((node) => node.type === "p" && node.props.children === "BASEKNOW-D-4770 检查完成"));
});

test("配置字段详情区分修改新增删除和null，行号只显示实际记录", () => {
  const changes = [
    {
      key: "robot_port",
      before: 18778,
      after: 18777,
      before_exists: true,
      after_exists: true,
      path: "/home/robot/config.json",
      line: 42,
      backup: "/home/robot/config.json.bak",
      before_sha256: "a".repeat(64),
      after_sha256: "b".repeat(64),
    },
    { key: "new_flag", after: false, before_exists: false, after_exists: true, path: "/home/robot/config.json" },
    {
      key: "old_flag",
      before: null,
      before_exists: true,
      after_exists: false,
      path: "/home/robot/config.json",
      before_line: 12,
    },
    {
      key: "nullable",
      before: null,
      after: "ready",
      before_exists: true,
      after_exists: true,
      path: "/home/robot/config.json",
    },
    { key: "unrecorded", before_exists: true, after_exists: true, path: "/home/robot/config.json" },
  ];
  const tree = render(
    [
      {
        ...events[0],
        remote_process: {
          summary: "配置修改完成",
          command: { kind: "patch_file", path: "/home/robot/config.json", changes },
        },
      },
    ],
    []
  );
  const details = nodes(tree).find(
    (node) =>
      node.type === "details" &&
      [node.props.children].flat().some((child) => child?.type === "summary" && child.props.children === "查看操作详情")
  );
  const text = nodes(details)
    .flatMap((node) => [node.props?.children].flat())
    .filter((value) => typeof value === "string" || typeof value === "number")
    .join("");
  for (const value of [
    '"robot_port": 18778',
    '"robot_port": 18777',
    "新增字段",
    '"new_flag": false',
    "字段不存在",
    "删除字段",
    '"old_flag": null',
    '"nullable": null',
    '"nullable": "ready"',
    "字段值未记录",
    "/home/robot/config.json",
    "第42行",
    "行号未记录",
    "config.json.bak",
    "a".repeat(64),
    "b".repeat(64),
  ])
    assert.ok(text.includes(value), value);
  assert.equal(details.props.open, undefined);
});

test("读取配置详情的任务不重复缺陷编号，校验值不误称修改且技术记录二级折叠", () => {
  const note = "Agent 读取配置：工具执行完成；任务 95f89e89-3d92-4f6c-a6aa-9b95fddfcd88";
  const tree = render(
    [
      {
        ...events[0],
        note,
        remote_process: {
          summary: "BASEKNOW-D-481 第1轮诊断修复 · 读取配置：完成",
          defect_code: "BASEKNOW-D-481",
          round: 1,
          command: { kind: "read_file", path: "/home/robot/config.json", sha256: "a".repeat(64) },
          run_id: "95f89e89-3d92-4f6c-a6aa-9b95fddfcd88",
        },
      },
    ],
    [],
    { code: "BASEKNOW-D-481" }
  );
  const details = nodes(tree).find(
    (node) =>
      node.type === "details" &&
      [node.props.children].flat().some((child) => child?.type === "summary" && child.props.children === "查看操作详情")
  );
  const technical = nodes(details).find(
    (node) =>
      node.type === "details" &&
      [node.props.children].flat().some((child) => child?.type === "summary" && child.props.children === "技术记录")
  );
  assert.ok(technical);
  assert.equal(technical.props.open, undefined);
  const text = primaryText(details);
  assert.match(text, /第1轮诊断修复/);
  assert.match(text, /文件校验值/);
  assert.doesNotMatch(text, /修改后|BASEKNOW-D-481|95f89e89/);
  assert.match(JSON.stringify(technical), /BASEKNOW-D-481/);
  assert.match(JSON.stringify(technical), /工具执行完成/);
});

test("连续同任务成功检查默认折叠，失败检查与修复仍在一级且原序保留", () => {
  const event = (id, stage = "inspect", ok = true) => ({
    ...events[0],
    id,
    remote_process: {
      summary: `检查${id}`,
      stage,
      run_id: "same-run",
      command: { status: "done", ok, exit_code: ok ? 0 : 1 },
    },
  });
  const tree = render([event("one"), event("two"), event("failed", "inspect", false), event("repair", "repair")], []);
  const group = nodes(tree).find(
    (node) =>
      node.type === "details" &&
      [node.props.children]
        .flat()
        .some((child) => child?.type === "summary" && JSON.stringify(child.props.children).includes("检查过程"))
  );
  assert.ok(group);
  assert.equal(group.props.open, undefined);
  assert.ok(JSON.stringify(group).includes("检查one") && JSON.stringify(group).includes("检查two"));
  assert.ok(!JSON.stringify(group).includes("检查failed") && !JSON.stringify(group).includes("检查repair"));
  const list = nodes(tree).find((node) => node.props?.["aria-label"] === "处理时间线");
  assert.equal([list.props.children].flat().flat().length, 3);
});

test("有diff时不重复父备份校验，读取校验折叠且成功退出码工具套话仅在技术记录", () => {
  const process = {
    summary: "读取配置完成",
    command: { kind: "read_file", path: "/config.json", sha256: "a".repeat(64), exit_code: 0 },
    details: "读取配置文件",
  };
  const tree = render([{ ...events[0], remote_process: process }], []);
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
  assert.ok(JSON.stringify(technical).includes("读取配置文件"));
  const patch = render(
    [
      {
        ...events[0],
        remote_process: {
          ...process,
          command: {
            kind: "patch_file",
            path: "/config.json",
            backup: "/config.bak",
            expected_sha256: "a".repeat(64),
            sha256: "b".repeat(64),
            changes: [
              {
                key: "enabled",
                before: false,
                after: true,
                before_exists: true,
                after_exists: true,
                backup: "/config.bak",
                before_sha256: "a".repeat(64),
                after_sha256: "b".repeat(64),
              },
            ],
          },
        },
      },
    ],
    []
  );
  assert.equal(
    nodes(patch).some((node) => node.type === "dt" && node.props.children === "备份与文件校验"),
    false
  );
});

test("实际run回执复用命令结果分栏，说明保留技术记录，配置diff优先", () => {
  const process = {
    summary: "验证完成",
    stage: "verify",
    command: {
      kind: "run",
      argv: ["robot_peer", "verify"],
      stdout: "verified=true",
      stderr: "",
      exit_code: 0,
      status: "done",
      ok: true,
    },
    details: "完整旧执行说明",
  };
  const tree = render([{ ...events[0], remote_process: process }], []);
  const execution = nodes(tree).find((node) => node.props?.["aria-label"] === "命令执行记录");
  assert.ok(execution);
  assert.match(JSON.stringify(execution), /robot_peer verify/);
  assert.match(JSON.stringify(execution), /verified=true/);
  assert.ok(!nodes(tree).some((node) => node.type === "dt" && node.props.children === "命令参数"));
  assert.ok(!nodes(tree).some((node) => node.type === "dt" && node.props.children === "执行说明"));
  const technical = nodes(tree).find(
    (node) =>
      node.type === "details" &&
      [node.props.children].flat().some((child) => child?.type === "summary" && child.props.children === "技术记录")
  );
  assert.match(JSON.stringify(technical), /完整旧执行说明/);
  process.command.changes = [{ path: "/config.json", key: "enabled", before: false, after: true }];
  const changed = render([{ ...events[0], remote_process: process }], []);
  assert.ok(nodes(changed).some((node) => node.props?.["aria-label"] === "配置差异"));
  assert.ok(nodes(changed).some((node) => node.props?.["aria-label"] === "命令执行记录"));
  const executionDetails = nodes(changed).find(
    (node) =>
      node.type === "details" &&
      [node.props.children]
        .flat()
        .some((child) => child?.type === "summary" && [child.props.children].flat().includes("执行详情"))
  );
  assert.ok(executionDetails);
  assert.equal(executionDetails.props.open, undefined);
});
