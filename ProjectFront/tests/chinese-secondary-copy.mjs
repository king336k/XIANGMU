import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
// Evaluate the real confirmation guard with both entered fields; no destructive callback is run.
function canDelete(path, values, resource) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8");
  const ast = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let expression;
  function find(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(ast) === "canDelete") expression = node.initializer.getText(ast);
    ts.forEachChild(node, find);
  }
  find(ast);
  assert.ok(expression);
  return new Function("watch", "project", "data", `return ${expression}`)((key) => values[key], resource, resource);
}
test("中文删除确认仍须同时匹配完整名称和确认短语", () => {
  for (const [path, nameKey, phrase] of [
    ["../core/components/project/delete-project-modal.tsx", "projectName", "删除此项目"],
    ["../core/components/workspace/delete-workspace-form.tsx", "workspaceName", "删除此工作空间"],
  ]) {
    assert.equal(canDelete(path, { [nameKey]: "验收对象", confirmDelete: phrase }, { name: "验收对象" }), true);
    assert.equal(canDelete(path, { [nameKey]: "其他名称", confirmDelete: phrase }, { name: "验收对象" }), false);
    assert.equal(canDelete(path, { [nameKey]: "验收对象", confirmDelete: "" }, { name: "验收对象" }), false);
  }
});
test("季度时间轴显示数字月份，周末标识保留用于布局计算", async () => {
  const source = readFileSync(new URL("../core/components/gantt-chart/data/index.ts", import.meta.url), "utf8");
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const exports = {};
  new Function("require", "exports", code)((id) => id === "@plane/types" ? { EStartOfTheWeek: { SUNDAY: 0 } } : require(id), exports);
  assert.deepEqual(exports.quarters.map((row) => row.title), ["1–3月", "4–6月", "7–9月", "10–12月"]);
  assert.equal(exports.weeks[0].shortTitle, "sun");
  assert.equal(exports.weeks[6].shortTitle, "sat");
});
