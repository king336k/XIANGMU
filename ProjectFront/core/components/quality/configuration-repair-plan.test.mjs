import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../../../package.json", import.meta.url));
const ts = require("typescript");
const React = require("react");

function nodes(tree) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
function text(tree) {
  if (tree == null || typeof tree === "boolean") return "";
  if (typeof tree !== "object") return String(tree);
  if (Array.isArray(tree)) return tree.map(text).join("");
  return text(tree.props?.children);
}
const proposal = {
  source_run_id: "private-source-id",
  plan_digest: "private-digest-one",
  robot: "dexforce",
  observed_at: "2026-11-20T03:00:00Z",
  expires_at: "2099-11-20T03:15:00Z",
  device: { username: "cfys-025", ip_address: "10.10.10.76" },
  path: "/opt/engram/runtime/teleop/robot_description.yaml",
  changes: [{ key: "initial_joint_states.right_arm[0]", before: 5.3065, after: 0.3065 }],
  can_approve: true,
};

function harness({
  current = proposal,
  disabled = false,
  write = async () => ({ id: "new-run", status: "queued" }),
} = {}) {
  const state = [],
    refs = [];
  let cursor = 0,
    refCursor = 0,
    submitted;
  const exports = {};
  const model = { current };
  const reads = [],
    writes = [];
  const source = readFileSync(new URL("./configuration-repair-plan.tsx", import.meta.url), "utf8");
  new Function(
    "require",
    "exports",
    ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )(
    (name) =>
      ({
        react: {
          ...React,
          useState(initial) {
            const i = cursor++;
            if (!(i in state)) state[i] = initial;
            return [
              state[i],
              (next) => {
                state[i] = next;
              },
            ];
          },
          useRef(initial) {
            const i = refCursor++;
            return (refs[i] ||= { current: initial });
          },
        },
        swr: {
          default(key) {
            reads.push(key);
            return { data: { proposal: model.current } };
          },
        },
        "./api": {
          qualityApi: {
            read() {},
            async write(url, body) {
              writes.push({ url, body });
              return write(url, body);
            },
          },
          errorMessage: (error) => error.message,
        },
        "../remote-diagnostics/types": { remoteDiagnosticsBase: "/api/quality-auth/remote-diagnostics/" },
      })[name] ?? require(name),
    exports
  );
  function render() {
    cursor = 0;
    refCursor = 0;
    return exports.ConfigurationRepairPlan({
      defectId: "defect-502",
      disabled,
      onSubmitted(run) {
        submitted = run;
      },
    });
  }
  function click(tree, label) {
    const button = nodes(tree).find((node) => node.type === "button" && text(node) === label);
    assert.ok(button, label);
    return button.props.onClick();
  }
  return {
    render,
    click,
    model,
    reads,
    writes,
    get submitted() {
      return submitted;
    },
  };
}

test("plan is collapsed and never approves from initial render or missing proposal", () => {
  const h = harness();
  const tree = h.render();
  assert.match(JSON.stringify(tree), /查看修复计划/);
  assert.doesNotMatch(JSON.stringify(tree), /5\.3065|private-digest|private-source/);
  assert.equal(h.writes.length, 0);
  assert.equal(harness({ current: null }).render(), null);
  assert.match(text(tree), /待确认/);
  assert.doesNotMatch(JSON.stringify(tree), /animate-spin/);
});

test("expanded plan shows real before/after and requires explicit applicability confirmation", async () => {
  const h = harness();
  h.click(h.render(), "查看修复计划");
  let tree = h.render();
  assert.match(text(tree), /cfys-025@10\.10\.10\.76/);
  assert.match(JSON.stringify(tree), /5\.3065/);
  assert.match(JSON.stringify(tree), /0\.3065/);
  assert.match(JSON.stringify(tree), /修改前/);
  assert.match(JSON.stringify(tree), /修改后/);
  assert.match(JSON.stringify(tree), /不执行机器人复位/);
  assert.doesNotMatch(JSON.stringify(tree), /private-digest|private-source/);
  let button = nodes(tree).find((node) => node.type === "button" && text(node) === "确认修复");
  assert.equal(button.props.disabled, true);
  const checkbox = nodes(tree).find((node) => node.type === "input" && node.props.type === "checkbox");
  assert.equal(checkbox.props.checked, false);
  checkbox.props.onChange({ target: { checked: true } });
  tree = h.render();
  button = nodes(tree).find((node) => node.type === "button" && text(node) === "确认修复");
  assert.equal(button.props.disabled, false);
  await button.props.onClick();
  assert.deepEqual(h.writes, [
    {
      url: "/api/quality-auth/remote-diagnostics/configuration-plans/",
      body: {
        source_run_id: proposal.source_run_id,
        plan_digest: proposal.plan_digest,
        confirmation: "confirmed",
      },
    },
  ]);
  assert.deepEqual(h.submitted, { id: "new-run", status: "queued" });
});

test("double click cannot submit a second mutation and changed plans require confirmation again", async () => {
  let finish;
  const h = harness({
    write: () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  });
  h.click(h.render(), "查看修复计划");
  nodes(h.render())
    .find((node) => node.type === "input")
    .props.onChange({ target: { checked: true } });
  const tree = h.render();
  h.click(tree, "确认修复");
  h.click(tree, "确认修复");
  assert.equal(h.writes.length, 1);
  finish({ id: "accepted", status: "queued" });
  await new Promise((resolve) => setImmediate(resolve));
  h.model.current = { ...proposal, plan_digest: "private-digest-two" };
  const changed = h.render();
  assert.equal(nodes(changed).find((node) => node.type === "input").props.checked, false);
});

test("unapproved, expired and busy plans stay reviewable but cannot be submitted", () => {
  for (const options of [
    { current: { ...proposal, can_approve: false, blocked_reason: "executor_update_required" } },
    { current: { ...proposal, expires_at: "2020-01-01T00:00:00Z" } },
    { disabled: true },
  ]) {
    const h = harness(options);
    h.click(h.render(), "查看修复计划");
    const tree = h.render();
    assert.equal(nodes(tree).find((node) => node.type === "button" && text(node) === "确认修复").props.disabled, true);
    assert.equal(h.writes.length, 0);
  }
});

test("plan header gives short pending, expired, update and submitted states without auto approval", async () => {
  for (const [overrides, expected] of [
    [{}, "待确认"],
    [{ expires_at: "2020-01-01T00:00:00Z" }, "已失效"],
    [{ can_approve: false, blocked_reason: "请先更新 DAQ，再重新诊断。" }, "需更新"],
    [{ can_approve: false, blocked_reason: "executor_update_required" }, "需更新"],
    [{ can_approve: false, blocked_reason: "本轮计划已提交。" }, "已提交"],
    [{ can_approve: false, blocked_reason: "设备连接已变化，请重新诊断。" }, "暂不可执行"],
  ]) {
    const h = harness({ current: { ...proposal, ...overrides } });
    assert.match(text(h.render()), new RegExp(expected));
    assert.equal(h.writes.length, 0);
  }
  const submitted = harness();
  submitted.click(submitted.render(), "查看修复计划");
  nodes(submitted.render())
    .find((node) => node.type === "input")
    .props.onChange({ target: { checked: true } });
  await submitted.click(submitted.render(), "确认修复");
  assert.match(text(submitted.render()), /已提交/);
});

test("failed submit keeps the plan visible and allows an explicit retry", async () => {
  let calls = 0;
  const h = harness({
    write: async () => {
      if (++calls === 1) throw new Error("配置已变化，请重新诊断");
      return { id: "retry", status: "queued" };
    },
  });
  h.click(h.render(), "查看修复计划");
  nodes(h.render())
    .find((node) => node.type === "input")
    .props.onChange({ target: { checked: true } });
  await h.click(h.render(), "确认修复");
  assert.match(JSON.stringify(h.render()), /配置已变化，请重新诊断/);
  assert.match(JSON.stringify(h.render()), /5\.3065/);
  await h.click(h.render(), "确认修复");
  assert.equal(h.writes.length, 2);
  assert.equal(h.submitted.id, "retry");
});

test("backend refusal stays readable and generic fields do not become a joint-only form", () => {
  const h = harness({
    current: {
      ...proposal,
      robot: "other-robot",
      can_approve: false,
      blocked_reason: "请先更新 DAQ，再重新诊断。",
      changes: [{ key: "calibration.left[2]", before: 8.5, after: 0.25 }],
    },
  });
  h.click(h.render(), "查看修复计划");
  const tree = h.render();
  assert.match(text(tree), /请先更新 DAQ，再重新诊断/);
  assert.match(text(tree), /calibration.left\[2\]/);
  assert.doesNotMatch(text(tree), /right_arm|5.3065|0.3065/);
});
