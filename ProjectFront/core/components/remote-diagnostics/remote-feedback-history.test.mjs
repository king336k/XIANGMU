import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../../../package.json", import.meta.url));
const ts = require("typescript");
const React = require("react");
function load(file, mocks = {}) {
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
const summaries = load("../quality/report-summary.ts");
function harness() {
  let expanded = null;
  const { RemoteFeedbackHistory } = load("./remote-feedback-history.tsx", {
    react: {
      ...React,
      useState: () => [
        expanded,
        (value) => {
          expanded = value;
        },
      ],
    },
    "@plane/utils": { renderNumericDateTime: (value) => value },
    "../quality/report-summary": summaries,
  });
  return (replies, page = 1, feedbackId = "feedback") => RemoteFeedbackHistory({ replies, page, feedbackId });
}
function nodes(tree) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
const reply = (id, content = "结论：现场检查正常。") => ({
  id,
  content: `Agent 远程处理：验证通过\n${content}`,
  created_at: `2026-11-19T${id === "latest" ? "22" : "21"}:57:00Z`,
});

test("history defaults only latest open and does not leave old open after a new round", () => {
  const render = harness();
  const records = [reply("latest"), reply("old")];
  const first = nodes(render(records)).filter((node) => node.type === "button");
  assert.deepEqual(
    first.map((button) => button.props["aria-expanded"]),
    [true, false]
  );
  first[1].props.onClick();
  assert.deepEqual(
    nodes(render(records))
      .filter((node) => node.type === "button")
      .map((button) => button.props["aria-expanded"]),
    [false, true]
  );
  assert.deepEqual(
    nodes(render([reply("new"), ...records]))
      .filter((node) => node.type === "button")
      .map((button) => button.props["aria-expanded"]),
    [true, false, false]
  );
  assert.equal(
    nodes(render([reply("new"), ...records, reply("older")], 2)).some(
      (node) => node.type === "button" && node.props["aria-expanded"]
    ),
    false
  );
});

test("summary uses source sentences and points while exact location and all raw evidence remain available", () => {
  const location = "robot177 · /home/operator/runtime/collector.json:42 · telemetry_enabled false→true";
  const checksum = "a".repeat(64);
  const original = reply(
    "latest",
    `结论：模拟采集链路正常。未复现503。\n原因与证据：硬件原因尚未确认。\n已执行操作：读取当前配置。ROSA 检查 --verbose。\n修改位置：${location}\n复测：检查通过。\n后续方案：无需重启。\n详细证据与处理过程：\nSHA256 ${checksum}`
  );
  const tree = harness()([original]);
  const preview = nodes(tree).find((node) => node.type === "dl");
  const bullets = nodes(preview).find((node) => node.props?.["aria-label"] === "处理结论要点");
  assert.deepEqual(
    nodes(bullets)
      .filter((node) => node.type === "li")
      .map((node) => node.props.children),
    ["模拟采集链路正常。", "未复现503。"]
  );
  assert.match(JSON.stringify(preview), /硬件原因尚未确认/);
  assert.match(JSON.stringify(preview), /collector.json:42 · telemetry_enabled false→true/);
  assert.ok(!JSON.stringify(preview).includes(checksum));
  const evidence = nodes(tree).find((node) => node.type === "details");
  assert.equal(evidence.props.open, undefined);
  assert.equal(nodes(evidence).find((node) => node.type === "pre").props.children, original.content);
});
