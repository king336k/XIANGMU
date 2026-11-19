import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const exports = {};
new Function(
  "require",
  "exports",
  ts.transpileModule(
    readFileSync(new URL("../core/components/quality/command-execution-result.tsx", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }
  ).outputText
)(require, exports);
const { CommandExecutionResult } = exports;
const nodes = (tree) =>
  !tree || typeof tree !== "object"
    ? []
    : Array.isArray(tree)
      ? tree.flatMap(nodes)
      : [tree, ...nodes(tree.props?.children)];
const text = (tree) =>
  tree === null || tree === undefined || tree === false
    ? ""
    : typeof tree !== "object"
      ? String(tree)
      : Array.isArray(tree)
        ? tree.map(text).join("")
        : text(tree.props?.children);
const region = (tree, name) => nodes(tree).find((node) => node.props?.["aria-label"] === name);

test("successful command shows real argv and output without claiming a business repair", () => {
  const tree = CommandExecutionResult({
    command: {
      argv: ["python", "-m", "pip", "install", "package name"],
      status: "done",
      exit_code: 0,
      stdout: "Already satisfied",
    },
    target: "robot@10.0.0.177",
  });
  const left = region(tree, "执行命令"),
    right = region(tree, "执行结果");
  assert.ok(left && right);
  assert.match(text(left), /python -m pip install 'package name'/);
  assert.match(text(tree), /robot@10.0.0.177/);
  assert.match(text(right), /命令执行完成，业务结果见复测/);
  assert.match(text(right), /Already satisfied/);
  assert.doesNotMatch(text(tree), /修改前|修改后|安装成功|修复成功/);
  assert.match(left.props.className, /bg-danger-subtle/);
  assert.match(right.props.className, /bg-success-subtle/);
  assert.match(JSON.stringify(tree), /sm:grid-cols-2/);
});

test("nonzero exits timeouts and failed receipts show failure without inventing verification", () => {
  for (const command of [
    { status: "done", exit_code: 1, stderr: "permission denied" },
    { timed_out: true },
    { status: "done", exit_code: 0, ok: false },
  ]) {
    const right = region(CommandExecutionResult({ command }), "执行结果");
    assert.match(right.props.className, /bg-danger-subtle/);
    assert.doesNotMatch(text(right), /命令执行完成|复测通过/);
  }
});

test("missing exit or unfinished status remains unconfirmed even with zero or optimistic stdout", () => {
  for (const command of [
    { status: "pending", exit_code: 0 },
    { exit_code: 0 },
    { status: "done" },
    { status: "delivered", stdout: "success" },
  ]) {
    const right = region(CommandExecutionResult({ command }), "执行结果");
    assert.match(text(right), /执行回执待确认/);
    assert.doesNotMatch(right.props.className, /bg-success-subtle/);
    assert.doesNotMatch(text(right), /命令执行完成/);
  }
});

test("each output previews only the final twelve actual lines and keeps full output collapsed", () => {
  const output = Array.from({ length: 18 }, (_, index) => `line-${index + 1}`).join("\n") + "\n";
  const tree = CommandExecutionResult({ command: { status: "done", exit_code: 0, stdout: output, stderr: output } });
  for (const label of ["标准输出", "标准错误"]) {
    const preview = region(tree, `${label}摘要`);
    assert.equal(text(preview).split("\n").length, 12);
    assert.equal(text(preview).split("\n")[0], "line-7");
    assert.equal(text(preview).split("\n").at(-1), "line-18");
    const details = nodes(tree).find((node) => node.type === "details" && text(node).startsWith(`完整${label}`));
    assert.ok(details);
    assert.equal(details.props.open, undefined);
    assert.ok(nodes(details).some((node) => node.type === "pre" && node.props.children === output));
  }
});

test("output and argv are text escaped by React and redacted placeholders stay unchanged", () => {
  const tree = CommandExecutionResult({
    command: {
      argv: ["tool", "--token", "[已隐藏]"],
      status: "done",
      exit_code: 0,
      stdout: '<img src=x onerror="alert(1)">',
    },
  });
  const markup = require("react-dom/server").renderToStaticMarkup(tree);
  assert.match(markup, /&lt;img/);
  assert.doesNotMatch(markup, /<img/);
  assert.match(text(tree), /\[已隐藏\]/);
  assert.ok(nodes(tree).every((node) => !node.props?.dangerouslySetInnerHTML));
});

test("actual execution steps replace the wrapper and keep each actual outcome", () => {
  const tree = CommandExecutionResult({
    target: "collector@10.0.0.195",
    command: {
      argv: ["python3", "action_acceptance.py", "repair"],
      status: "done",
      exit_code: 0,
      stdout: "wrapper summary must not duplicate real steps",
      execution_steps: [
        {
          argv: ["venv/bin/python", "-m", "pip", "install", "--no-index", "colorama.whl"],
          stdout: "Successfully installed colorama-0.4.6",
          exit_code: 0,
          ok: true,
          status: "done",
        },
        {
          argv: ["systemctl", "--user", "restart", "engram-diagnostic-action-test.service"],
          stderr: "unit failed",
          exit_code: 1,
          ok: false,
          status: "done",
        },
      ],
    },
  });
  const commandRegions = nodes(tree).filter((node) => node.props?.["aria-label"] === "执行命令");
  const resultRegions = nodes(tree).filter((node) => node.props?.["aria-label"] === "执行结果");
  assert.equal(commandRegions.length, 2);
  assert.match(text(commandRegions[0]), /pip install --no-index colorama.whl/);
  assert.match(text(commandRegions[1]), /systemctl --user restart/);
  assert.match(resultRegions[0].props.className, /bg-success-subtle/);
  assert.match(resultRegions[1].props.className, /bg-danger-subtle/);
  assert.doesNotMatch(text(tree), /action_acceptance.py|wrapper summary/);
  assert.match(text(tree), /collector@10.0.0.195/);
});

test("empty steps fall back to the actual wrapper and nested untrusted steps are not interpreted", () => {
  const fallback = CommandExecutionResult({
    command: { argv: ["wrapper"], execution_steps: [], status: "done", exit_code: 0 },
  });
  assert.match(text(fallback), /wrapper/);
  const tree = CommandExecutionResult({
    command: {
      execution_steps: [{ argv: ["real-step"], timed_out: true, execution_steps: [{ argv: ["not-an-actual-step"] }] }],
    },
  });
  assert.match(text(tree), /real-step|命令执行超时/);
  assert.doesNotMatch(text(tree), /not-an-actual-step/);
  assert.equal(nodes(tree).filter((node) => node.props?.["aria-label"] === "执行命令").length, 1);
});

test("long single-line outputs are bounded and the exact original stays collapsed", () => {
  const output = "actual-output:" + "x".repeat(4096);
  const tree = CommandExecutionResult({ command: { status: "done", exit_code: 0, stdout: output, stderr: output } });
  for (const label of ["标准输出", "标准错误"]) {
    assert.ok(text(region(tree, `${label}摘要`)).length <= 200);
    const details = nodes(tree).find((node) => node.type === "details" && text(node).startsWith(`完整${label}`));
    assert.ok(details && details.props.open === undefined);
    assert.ok(nodes(details).some((node) => node.type === "pre" && node.props.children === output));
  }
  assert.match(text(tree), /输出节选/);
});

test("minified JSON is formatted before tailing and every summary stays within twelve lines and 1000 characters", () => {
  const value = Object.fromEntries(
    Array.from({ length: 30 }, (_, index) => [`field_${index}`, `actual-${index}:` + "z".repeat(220)])
  );
  const output = JSON.stringify(value);
  const tree = CommandExecutionResult({ command: { status: "done", exit_code: 0, stdout: output } });
  const preview = text(region(tree, "标准输出摘要"));
  assert.ok(preview.split("\n").length <= 12);
  assert.ok(preview.length <= 1000);
  assert.ok(preview.split("\n").every((line) => line.length <= 200));
  assert.match(preview, /field_29/);
  assert.doesNotMatch(preview, /field_0"/);
  assert.match(text(tree), /输出节选/);
  const details = nodes(tree).find((node) => node.type === "details");
  assert.ok(nodes(details).some((node) => node.type === "pre" && node.props.children === output));
});

test("large receipt sequence numbers remain exact rather than being rounded by JSON formatting", () => {
  const output = '{"sequence":1795001199827232052,"verified":true}';
  const tree = CommandExecutionResult({ command: { status: "done", exit_code: 0, stdout: output } });
  assert.equal(text(region(tree, "标准输出摘要")), output);
});
