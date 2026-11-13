import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
function data() {
  const exports = {};
  new Function(
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/settings/module-owner-data.ts", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }
    ).outputText
  )(exports);
  return exports;
}
test("创建账号只能在已授予技术员的工作空间选择模块责任，项目范围去重", () => {
  const { technicianWorkspaces } = data();
  const pending = {
    p1: { id: "p1", workspace_id: "w1", roles: ["TECHNICIAN"], access_role: 15 },
    p2: { id: "p2", workspace_id: "w1", roles: ["TECHNICIAN"], access_role: 20 },
    p3: { id: "p3", workspace_id: "w2", roles: ["REGRESSION_TESTER"], access_role: 15 },
    p4: { id: "p4", workspace_id: "w3", roles: ["TECHNICIAN"], access_role: 5 },
  };
  assert.deepEqual(technicianWorkspaces("project", pending), ["w1"]);
  assert.deepEqual(technicianWorkspaces("none", pending), []);
  assert.deepEqual(technicianWorkspaces("workspace", { w: { id: "w", roles: ["TECHNICIAN"], access_role: 15 } }), [
    "w",
  ]);
});
test("选中和取消模块保持其他工作空间绑定，撤销技术员范围会排除旧绑定", () => {
  const { toggleModuleOwner, validModuleBindings } = data();
  const bindings = [
    { workspace_id: "w1", module_key: "daq" },
    { workspace_id: "w2", module_key: "teleop" },
  ];
  assert.deepEqual(toggleModuleOwner(bindings, "w1", "daq", false), [bindings[1]]);
  assert.deepEqual(toggleModuleOwner(bindings, "w1", "daq", true), bindings);
  assert.deepEqual(toggleModuleOwner(bindings, "w1", "teleop", true), [
    ...bindings,
    { workspace_id: "w1", module_key: "teleop" },
  ]);
  assert.deepEqual(validModuleBindings(bindings, ["w1"]), [bindings[0]]);
});
