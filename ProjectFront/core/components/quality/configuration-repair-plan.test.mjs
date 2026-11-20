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
  run = null,
  onRestoredRun,
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
    writes = [],
    effects = [];
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
          useEffect(effect) {
            effects.push(effect);
          },
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
        "./configuration-plan-result": {
          ConfigurationPlanResult: ({ run: resultRun }) => React.createElement("p", null, resultRun?.status || ""),
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
      run,
      onHistory() {},
      onRestoredRun,
      onSubmitted(acceptedRun) {
        submitted = acceptedRun;
      },
    });
  }
  function click(tree, label) {
    if (label === "配置修复计划") {
      const details = nodes(tree).find((node) => node.type === "details");
      assert.ok(details, "native plan disclosure");
      const summary = nodes(details).find((node) => node.type === "summary");
      assert.ok(summary && text(summary).includes(label), label);
      return details.props.onToggle({ currentTarget: { open: !details.props.open } });
    }
    const button = nodes(tree).find((node) => node.type === "button" && text(node) === label);
    assert.ok(button, label);
    return button.props.onClick();
  }
  return {
    render,
    runEffects() {
      effects.splice(0).forEach((effect) => effect());
    },
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
  const details = nodes(tree).find((node) => node.type === "details");
  assert.ok(details, "plan uses the same native disclosure as field versions");
  assert.equal(details.props.open, false);
  assert.match(text(tree), /配置修复计划/);
  assert.doesNotMatch(text(tree), /查看修复计划|收起修复计划/);
  assert.doesNotMatch(JSON.stringify(tree), /5\.3065|private-digest|private-source/);
  assert.equal(h.writes.length, 0);
  assert.equal(harness({ current: null }).render(), null);
  assert.match(text(tree), /待确认/);
  assert.doesNotMatch(JSON.stringify(tree), /animate-spin/);
});

test("plan title row opens and closes the native disclosure without approving", () => {
  const h = harness();
  let tree = h.render();
  let details = nodes(tree).find((node) => node.type === "details");
  assert.ok(details, "native details gives keyboard Enter/Space disclosure behavior");
  assert.equal(details.props.open, false);
  assert.equal(nodes(tree).find((node) => node.type === "summary").props["aria-expanded"], false);
  h.click(tree, "配置修复计划");
  tree = h.render();
  details = nodes(tree).find((node) => node.type === "details");
  assert.equal(details.props.open, true);
  assert.equal(nodes(tree).find((node) => node.type === "summary").props["aria-expanded"], true);
  assert.match(text(tree), /修改前.*修改后/u);
  h.click(tree, "配置修复计划");
  tree = h.render();
  assert.equal(nodes(tree).find((node) => node.type === "details").props.open, false);
  assert.doesNotMatch(text(tree), /修改前|确认修复/);
  assert.equal(h.writes.length, 0);
});

test("expanded plan shows real before/after and requires explicit applicability confirmation", async () => {
  const h = harness();
  h.click(h.render(), "配置修复计划");
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
  h.click(h.render(), "配置修复计划");
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
    h.click(h.render(), "配置修复计划");
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
  submitted.click(submitted.render(), "配置修复计划");
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
  h.click(h.render(), "配置修复计划");
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

test("submitted repair remains visible when the proposal disappears and follows the parent snapshot", () => {
  const run = { id: "confirmed-run", status: "running", queue: { stage: "verify" } };
  const h = harness({ current: null, run });
  assert.deepEqual(h.render().props.run, run);
  const restored = harness({
    current: { ...proposal, submitted_run: { id: "restored", status: "completed", result: { actual_write: false } } },
  });
  const result = nodes(restored.render()).find((node) => node.props?.run?.id === "restored");
  assert.ok(result, "the server-provided run remains directly reachable after refresh");
  assert.equal(restored.writes.length, 0);
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
  h.click(h.render(), "配置修复计划");
  const tree = h.render();
  assert.match(text(tree), /请先更新 DAQ，再重新诊断/);
  assert.match(text(tree), /calibration.left\[2\]/);
  assert.doesNotMatch(text(tree), /right_arm|5.3065|0.3065/);
});

test("another operator's submitted summary stays visible without starting their private run poll", () => {
  const restored = [];
  const run = {
    id: "other-run",
    can_follow: false,
    status: "completed",
    result: { actual_write: false, configuration_blocked_reason: "配置已变化。" },
  };
  const h = harness({ current: { ...proposal, submitted_run: run }, onRestoredRun: (value) => restored.push(value) });
  const tree = h.render();
  h.runEffects();
  assert.equal(restored.length, 0);
  assert.ok(nodes(tree).find((node) => node.props?.run?.id === "other-run"));
  const mine = harness({
    current: { ...proposal, submitted_run: { ...run, id: "my-run", can_follow: true } },
    onRestoredRun: (value) => restored.push(value),
  });
  mine.render();
  mine.runEffects();
  assert.equal(restored.length, 1);
  assert.equal(restored[0].id, "my-run");
});
