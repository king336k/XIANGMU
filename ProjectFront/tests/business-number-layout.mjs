import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const transpile = (path) =>
  ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
  }).outputText;
const load = async (path) => import(`data:text/javascript;base64,${Buffer.from(transpile(path)).toString("base64")}`);
test("需求独立编号，任务保留原序号；项目标识不写死", async () => {
  const { businessCode } = await load("../core/components/quality/business-code.ts");
  assert.equal(businessCode("DEMO", 7, { 7: 1, 8: 2 }), "DEMO-R-1");
  assert.equal(businessCode("DAQ", 8, { 7: 1, 8: 2 }), "DAQ-R-2");
  assert.equal(businessCode("TASK", 6, { 7: 1 }), "TASK-T-6");
});
test("默认英文状态中文展示，用户自定义状态保持原名", async () => {
  const { displayStateName } = await load("../core/components/issues/state-display.ts");
  assert.equal(displayStateName("Backlog"), "待排期");
  assert.equal(displayStateName("待产品确认"), "待产品确认");
  assert.equal(displayStateName("Custom QA stage"), "Custom QA stage");
});
