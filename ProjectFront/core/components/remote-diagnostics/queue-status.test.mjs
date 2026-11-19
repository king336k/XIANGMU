import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../../../package.json", import.meta.url));
const ts = require("typescript");
const React = require("react");

function module(file, mocks = {}, timers = setTimeout) {
  const exports = {};
  new Function(
    "require",
    "exports",
    "setTimeout",
    "clearTimeout",
    ts.transpileModule(readFileSync(new URL(file, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )(
    (name) => mocks[name] ?? require(name),
    exports,
    timers,
    () => {}
  );
  return exports;
}
const types = module("./types.ts");
const device = {
  id: "device",
  username: "caiji1",
  ip_address: "10.0.0.195",
  online: true,
  can_connect: true,
  capabilities: {},
};
const feedback = { id: "feedback", code: "D-474", title: "采集问题" };
function nodes(tree) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}

test("queue labels use real reason and positive position without inventing ETA or execution", () => {
  const label = types.agentRunStatusLabel;
  for (const [reason, expected] of [
    ["device_busy", "等待采集电脑空闲"],
    ["terminal_open", "等待终端关闭"],
    ["transfer_active", "等待文件传输完成"],
    ["worker_busy", "等待诊断资源空闲"],
  ])
    assert.equal(label({ status: "queued", queue: { reason, position: 0 } }), expected);
  assert.equal(label({ status: "queued", queue: { position: 2 } }), "排队中 · 前方 2 个任务");
  for (const position of [null, undefined, -1, 1.5, Number.NaN])
    assert.equal(label({ status: "queued", queue: { position } }), "排队中");
  assert.equal(label({ status: "queued" }), "排队中");
  for (const [stage, expected] of [
    ["inspect", "正在诊断"],
    ["repair", "正在修复"],
    ["verify", "正在复测"],
  ])
    assert.equal(label({ status: "running", queue: { stage } }), expected);
  assert.equal(label({ status: "running" }), "正在处理");
  assert.equal(label({ status: "cancelled" }), "已取消");
  assert.equal(label({ status: "timed_out" }), "处理超时");
});

function actions(run, write = async () => ({ id: "run", status: "queued" }), restoredRun = undefined) {
  let cursor = 0;
  const states = ["", run?.id || "", false, ""];
  const intervals = [];
  const runUrls = [];
  const api = module("../quality/agent-feedback-actions.tsx", {
    react: {
      ...React,
      useState: () => [states[cursor++], () => {}],
      useRef: (initial) => ({ current: initial }),
      useEffect() {},
    },
    swr: {
      default: (url, fetcher, config) => {
        if (url?.includes("agent-runs")) {
          intervals.push(config.refreshInterval);
          runUrls.push(url);
        }
        return {
          data: url?.includes("defect-targets")
            ? {
                results: [device],
                active_run: restoredRun,
                binding: { kind: "daq", state: "matched", device_id: device.id },
              }
            : run,
        };
      },
    },
    "./api": { qualityApi: { write }, errorMessage: (error) => error.message },
    "../remote-diagnostics/types": types,
  });
  return {
    tree: api.AgentFeedbackActions({ defectId: "feedback", active: true, onCompleted() {}, onHistory() {} }),
    intervals,
    runUrls,
  };
}

test("feedback actions display real queue, keep polling queued/running and stop at terminal status", () => {
  const queued = { id: "run", status: "queued", queue: { reason: "terminal_open", position: 2 } };
  const { tree, intervals } = actions(queued);
  assert.match(JSON.stringify(tree), /等待终端关闭 · 前方 2 个任务/);
  assert.match(JSON.stringify(tree), /animate-spin/);
  assert.ok(nodes(tree).some((node) => node.props?.role === "status" && node.props["aria-live"] === "polite"));
  for (const button of nodes(tree).filter(
    (node) => node.type === "button" && ["重新诊断", "继续处理", "重新验证"].includes(node.props.children)
  ))
    assert.equal(button.props.disabled, true);
  assert.equal(intervals[0](queued), 1500);
  assert.equal(intervals[0]({ status: "running" }), 1500);
  assert.equal(intervals[0]({ status: "failed" }), 0);
  assert.equal(intervals[0]({ status: "completed" }), 0);
  const failed = actions({ id: "run", status: "failed", error: "任务超时，未确认恢复" }).tree;
  assert.match(JSON.stringify(failed), /任务超时，未确认恢复/);
  assert.match(JSON.stringify(failed), /text-danger-primary/);
  assert.doesNotMatch(JSON.stringify(failed), /animate-spin/);
});

test("page refresh restores authoritative active run and polling without submitting another task", () => {
  let writes = 0;
  const restored = { id: "restored", status: "running", queue: { stage: "verify" } };
  const { tree, runUrls } = actions(
    undefined,
    async () => {
      writes++;
    },
    restored
  );
  assert.deepEqual(runUrls, ["/api/quality-auth/remote-diagnostics/agent-runs/restored/"]);
  assert.match(JSON.stringify(tree), /正在复测/);
  assert.match(JSON.stringify(tree), /animate-spin/);
  for (const button of nodes(tree).filter(
    (node) => node.type === "button" && ["重新诊断", "继续处理", "重新验证"].includes(node.props.children)
  ))
    assert.equal(button.props.disabled, true);
  assert.equal(writes, 0);
});

test("feedback actions prevent a second submit before React rerenders", async () => {
  let count = 0;
  let finish;
  const { tree } = actions(undefined, () => {
    count++;
    return new Promise((resolve) => {
      finish = resolve;
    });
  });
  const button = nodes(tree).find((node) => node.type === "button" && node.props.children === "重新诊断");
  button.props.onClick();
  button.props.onClick();
  assert.equal(count, 1);
  finish({ id: "run", status: "queued" });
  await new Promise((resolve) => setImmediate(resolve));
  button.props.onClick();
  assert.equal(count, 1, "accepted task stays guarded before the first polling snapshot arrives");
});

test("repair starts one continuous task and readonly actions explicitly preserve their non-mutating modes", async () => {
  await Promise.all(
    [
      ["继续处理", "repair"],
      ["重新诊断", "diagnose"],
      ["重新验证", "verify"],
    ].map(async ([label, mode]) => {
      const writes = [];
      const { tree } = actions(undefined, async (url, body) => {
        writes.push(body);
        return { id: "one-task", status: "queued" };
      });
      const button = nodes(tree).find((node) => node.type === "button" && node.props.children === label);
      assert.ok(button, label);
      button.props.onClick();
      await new Promise((resolve) => setImmediate(resolve));
      assert.equal(writes.length, 1);
      assert.equal(writes[0].mode, mode);
      assert.match(JSON.stringify(tree), /同一任务|自动复测/);
      if (mode !== "repair") assert.match(writes[0].problem, /禁止修改/);
    })
  );
});

test("completion label claims repair and retest only when both actual evidence flags are present", () => {
  assert.equal(
    types.agentRunStatusLabel({
      status: "completed",
      result: { repaired: true, verification_passed: true, outcome: "repaired" },
    }),
    "已修复并复测"
  );
  assert.equal(
    types.agentRunStatusLabel({
      status: "completed",
      result: { repaired: false, verification_passed: true, outcome: "verified" },
    }),
    "复测通过"
  );
  assert.equal(
    types.agentRunStatusLabel({ status: "completed", result: { repaired: false, outcome: "unresolved" } }),
    "处理完成"
  );
  assert.equal(types.agentRunStatusLabel({ status: "completed", result: { repaired: true } }), "处理完成");
});

test("device panel polls real queued stage through repair to completion and then stops", async () => {
  let cursor = 0;
  const pendingTimers = [];
  const effects = [];
  const changes = [];
  const states = [
    feedback,
    "排查",
    false,
    { id: "run", status: "queued", queue: { reason: "device_busy", position: 0 }, result: {} },
    "",
    1,
  ];
  const responses = [
    { id: "run", status: "running", queue: { stage: "repair" } },
    { id: "run", status: "completed", result: { repaired: true } },
  ];
  const api = module(
    "./agent-panel.tsx",
    {
      react: {
        ...React,
        useState: () => {
          const index = cursor++;
          return [states[index], (value) => changes.push([index, value])];
        },
        useRef: (initial) => ({ current: initial }),
        useEffect: (effect) => effects.push(effect),
      },
      swr: { default: () => ({ data: [], mutate() {} }) },
      "@/components/quality/api": {
        qualityApi: {
          async read() {
            return responses.shift();
          },
        },
        errorMessage: (error) => error.message,
      },
      "@/components/quality/shared": { fieldClass: "field" },
      "./types": types,
      "./feedback-picker": { FeedbackPicker: () => null },
      "./remote-feedback-history": { RemoteFeedbackHistory: () => null },
    },
    (callback) => {
      pendingTimers.push(callback);
      return pendingTimers.length;
    }
  );
  const tree = api.AgentPanel({ device });
  assert.match(JSON.stringify(tree), /等待采集电脑空闲/);
  assert.equal(
    nodes(tree).find((node) => node.type === "button" && node.props.children === "处理中").props.disabled,
    true
  );
  assert.doesNotMatch(JSON.stringify(tree), /暂无结果|"摘要"|"下一步"|正在诊断…/);
  for (const effect of effects) effect();
  assert.equal(pendingTimers.length, 1);
  pendingTimers.shift()();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(pendingTimers.length, 1);
  assert.equal(changes.find(([index, value]) => index === 3 && value.status === "running")[1].queue.stage, "repair");
  pendingTimers.shift()();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(pendingTimers.length, 0);
  assert.equal(changes.at(-1)[1].status, "completed");
});
