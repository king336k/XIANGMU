import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../../../package.json", import.meta.url));
const ts = require("typescript");
const React = require("react");
const device = {
  id: "station",
  username: "caiji1",
  ip_address: "10.0.0.195",
  online: true,
  can_connect: true,
  capabilities: {},
};
function nodes(tree) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
function load(file, mocks) {
  const exports = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(file, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((name) => mocks[name] ?? require(name), exports);
  return exports;
}
function renderTerminal(robot, states = []) {
  let cursor = 0;
  const effects = [],
    dependencies = [],
    changes = [];
  const { TerminalPanel } = load("./terminal-panel.tsx", {
    react: {
      ...React,
      useState: (initial) => {
        const index = cursor++;
        return [index < states.length ? states[index] : initial, (value) => changes.push([index, value])];
      },
      useRef: () => ({ current: null }),
      useEffect: (effect, values) => {
        effects.push(effect);
        dependencies.push(values);
      },
    },
    "@/components/quality/api": { qualityApi: {}, errorMessage: String },
    "./types": { remoteDiagnosticsBase: "/remote/" },
    "./terminal-connection": { TerminalConnection: () => null },
  });
  return { tree: TerminalPanel({ device, robot, onClose() {} }), changes, effects, dependencies };
}
test("robot terminal requires authoritative connected true and target changes carry no host or credentials", () => {
  for (const robot of [
    undefined,
    { host: "10.0.0.177", username: "robot" },
    { connected: false, host: "10.0.0.177" },
    { connected: true, username: "robot", host: "10.0.0.177" },
    { connected: true, host: "10.0.0.177", target_revision: "peer-one" },
    { connected: true, username: "robot", target_revision: "peer-one" },
    { connected: true, username: "robot", host: "10.0.0.177", target_revision: " " },
  ]) {
    const { tree } = renderTerminal(robot);
    const button = nodes(tree).find((node) => node.type === "button" && node.props.children === "机器人");
    assert.equal(button.props.disabled, true);
    assert.match(JSON.stringify(tree), /请先在DAQ连接机器人/);
  }
  const robot = { connected: true, target_revision: "peer-one", username: "robot", host: "10.0.0.177" };
  const { tree, changes } = renderTerminal(robot);
  nodes(tree)
    .find((node) => node.type === "button" && node.props.children === "机器人")
    .props.onClick();
  assert.deepEqual(changes, [
    [1, JSON.stringify(["peer-one", "robot", "10.0.0.177"])],
    [0, "robot"],
  ]);
});
test("robot title uses actual session identity and peer revision change closes instead of silently retargeting", () => {
  const oldKey = JSON.stringify(["peer-one", "robot", "10.0.0.177"]);
  const robot = { connected: true, target_revision: "peer-two", username: "new-robot", host: "10.0.0.178" };
  const result = renderTerminal(robot, [
    "robot",
    oldKey,
    { id: "old", identity: { username: "actual", host: "10.0.0.177" } },
    "open",
    "",
  ]);
  const heading = nodes(result.tree).find((node) => node.type === "h2");
  assert.match(JSON.stringify(heading), /actual/);
  assert.match(JSON.stringify(heading), /10.0.0.177/);
  assert.doesNotMatch(JSON.stringify(heading), /new-robot|10.0.0.178/);
  result.effects[0]();
  assert.ok(result.changes.some(([index, value]) => index === 3 && value === "closed"));
  assert.ok(result.changes.some(([index, value]) => index === 4 && value.includes("连接已变化")));
  assert.match(JSON.stringify(result.tree), /重新连接机器人/);
});

test("peer switch invalidates only robot effect and does not reconnect collector terminal", () => {
  const firstPeer = { connected: true, target_revision: "one", username: "robot", host: "10.0.0.177" };
  const nextPeer = { connected: true, target_revision: "two", username: "next", host: "10.0.0.178" };
  const collectorBefore = renderTerminal(firstPeer);
  const collectorAfter = renderTerminal(nextPeer);
  assert.deepEqual(collectorBefore.dependencies, collectorAfter.dependencies);
  const bound = JSON.stringify(["one", "robot", "10.0.0.177"]);
  const robotBefore = renderTerminal(firstPeer, ["robot", bound, null, "open", ""]);
  const robotAfter = renderTerminal(nextPeer, ["robot", bound, null, "open", ""]);
  assert.notDeepEqual(robotBefore.dependencies, robotAfter.dependencies);
  robotAfter.effects[0]();
  assert.deepEqual(robotAfter.changes.slice(0, 2), [
    [3, "closed"],
    [2, null],
  ]);
  assert.equal(
    robotAfter.changes.some(([index, value]) => index === 3 && value === "connecting"),
    false
  );
});
