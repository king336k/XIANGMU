import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const source = readFileSync(new URL("../core/components/quality/agent-feedback-actions.tsx", import.meta.url), "utf8");
const types = {};
new Function(
  "exports",
  ts.transpileModule(readFileSync(new URL("../core/components/remote-diagnostics/types.ts", import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
)(types);
const nodes = (tree) =>
  !tree || typeof tree !== "object"
    ? []
    : Array.isArray(tree)
      ? tree.flatMap(nodes)
      : [tree, ...nodes(tree.props?.children)];
const original = { id: "original", username: "original-user", ip_address: "10.0.0.199", online: true };
const unrelated = { id: "wrong", username: "wrong-user", ip_address: "10.0.0.195", online: true };
const ConfigurationRepairPlan = () => null;
function actions(data, selectedId = "wrong") {
  const exports = {},
    writes = [],
    states = [selectedId, "", false, "", null];
  let cursor = 0;
  new Function(
    "require",
    "exports",
    ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((id) => {
    if (id === "react")
      return {
        ...React,
        useState: () => [states[cursor++], () => {}],
        useEffect() {},
        useRef: (value) => ({ current: value }),
      };
    if (id === "swr") return { default: (url) => ({ data: url?.includes("defect-targets") ? data : undefined }) };
    if (id === "./api")
      return {
        qualityApi: {
          write: async (_, body) => {
            writes.push(body);
            return { id: "run", status: "queued" };
          },
        },
        errorMessage: String,
      };
    if (id === "../remote-diagnostics/types") return types;
    if (id === "./configuration-repair-plan") return { ConfigurationRepairPlan };
    return require(id);
  }, exports);
  const tree = exports.AgentFeedbackActions({ defectId: "D494", active: true, onCompleted() {}, onHistory() {} });
  return { tree, writes, html: renderToStaticMarkup(tree) };
}
test("DAQ source fixes the original station and ignores stale selection or malicious extra results", async () => {
  const { tree, writes, html } = actions({
    binding: { kind: "daq", state: "matched", device_id: original.id },
    results: [unrelated, original],
  });
  assert.doesNotMatch(html, /<select|wrong-user|10.0.0.195/);
  assert.match(html, /采集电脑：original-user@10.0.0.199/);
  assert.match(html, /在线/);
  nodes(tree)
    .find((node) => node.type === "button" && node.props.children === "继续处理")
    .props.onClick();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(writes[0].device_id, original.id);
});

test("approved plan and existing actions share the in-flight guard and release it only on rejection", () => {
  const { tree, writes } = actions({
    binding: { kind: "daq", state: "matched", device_id: original.id },
    results: [original],
  });
  const plan = nodes(tree).find((node) => node.type === ConfigurationRepairPlan);
  assert.ok(plan);
  assert.equal(plan.props.defectId, "D494");
  assert.equal(plan.props.onSubmitting(), true);
  assert.equal(plan.props.onSubmitting(), false);
  const inspect = nodes(tree).find((node) => node.type === "button" && node.props.children === "重新诊断");
  inspect.props.onClick();
  assert.equal(writes.length, 0);
  plan.props.onSettled(false);
  assert.equal(plan.props.onSubmitting(), true);
  plan.props.onSubmitted({ id: "approved-plan-run", status: "queued" });
  plan.props.onSettled(true);
  assert.equal(plan.props.onSubmitting(), false);
});
test("original offline missing or conflict never falls back to an online unrelated station", () => {
  for (const [state, device, expected] of [
    ["matched", { ...original, online: false }, "执行端断连"],
    ["missing", original, "执行端断连"],
    ["conflict", original, "接入信息不一致"],
  ]) {
    const { tree, writes, html } = actions({
      binding: { kind: "daq", state, device_id: original.id },
      results: [unrelated, device],
    });
    assert.doesNotMatch(html, /<select|wrong-user/);
    assert.match(html, new RegExp(expected));
    const button = nodes(tree).find((node) => node.type === "button" && node.props.children === "继续处理");
    assert.equal(button.props.disabled, true);
    button.props.onClick();
    assert.equal(writes.length, 0);
  }
});
test("no binding metadata fails closed and manual binding requires explicit selection", async () => {
  const unknown = actions({ results: [unrelated] });
  assert.equal(
    nodes(unknown.tree).find((node) => node.type === "button" && node.props.children === "继续处理").props.disabled,
    true
  );
  const manual = actions({ binding: { kind: "manual", state: "matched" }, results: [original] }, "");
  assert.match(manual.html, /<select/);
  assert.equal(
    nodes(manual.tree).find((node) => node.type === "button" && node.props.children === "继续处理").props.disabled,
    true
  );
  const explicit = actions({ binding: { kind: "manual", state: "matched" }, results: [original] }, original.id);
  nodes(explicit.tree)
    .find((node) => node.type === "button" && node.props.children === "继续处理")
    .props.onClick();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(explicit.writes[0].device_id, original.id);
});

test("historical same-computer verify-only binding allows only explicit verification", async () => {
  const { tree, writes, html } = actions({
    binding: { kind: "daq", state: "matched", device_id: original.id, execution_scope: "verify_only" },
    results: [original],
  });
  assert.match(html, /历史反馈已关联原电脑，仅支持重新验证/);
  for (const label of ["重新诊断", "继续处理"]) {
    const button = nodes(tree).find((node) => node.type === "button" && node.props.children === label);
    assert.equal(button.props.disabled, true);
    button.props.onClick();
  }
  assert.equal(writes.length, 0);
  const verify = nodes(tree).find((node) => node.type === "button" && node.props.children === "重新验证");
  assert.equal(verify.props.disabled, false);
  verify.props.onClick();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(writes.length, 1);
  assert.equal(writes[0].device_id, original.id);
  assert.equal(writes[0].mode, "verify");
});
