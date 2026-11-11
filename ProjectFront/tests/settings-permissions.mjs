import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const exp = {};
new Function(
  "exports",
  ts.transpileModule(
    readFileSync(new URL("../core/components/settings/settings-permissions.ts", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }
  ).outputText
)(exp);
test("有效管理员原生15可管理当前有效scope，普通native15与访客不被扩大", () => {
  assert.equal(exp.canManageSettings(false, true, 15, 15), true);
  assert.equal(exp.canManageSettings(false, true, 15), true);
  for (const admin of [false, undefined, "true", 1]) assert.equal(exp.canManageSettings(false, admin, 15, 15), false);
  assert.equal(exp.canManageSettings(false, true, 5, 15), false);
  assert.equal(exp.canManageSettings(false, true, 15, 5), false);
  assert.equal(exp.canManageSettings(false, true, undefined, 15), false);
  assert.equal(exp.canManageSettings(true, false, 20, 20), true);
});
