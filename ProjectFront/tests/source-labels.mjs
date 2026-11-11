import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
const code = ts.transpileModule(
  readFileSync(new URL("../core/components/quality/source-labels.ts", import.meta.url), "utf8"),
  { compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 } }
).outputText;
const { sourceRoleLabel, sourceStatusLabel } = await import(
  "data:text/javascript;base64," + Buffer.from(code).toString("base64")
);
test("来源岗位与状态使用实际业务中文", () => {
  assert.equal(sourceRoleLabel("Collector"), "数采员");
  assert.equal(sourceRoleLabel("Manager"), "数据经理");
  assert.equal(sourceStatusLabel("InProgress"), "进行中");
  assert.equal(sourceStatusLabel("ConvertFailed"), "转换失败");
  assert.equal(sourceStatusLabel("自定义中文状态"), "自定义中文状态");
});
