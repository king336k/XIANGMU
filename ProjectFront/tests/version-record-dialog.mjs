import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
const source = ts.transpileModule(
  readFileSync(new URL("../core/components/quality/version-record-dialog.tsx", import.meta.url), "utf8"),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }
).outputText;
function dialog(kind, mode, { manager = true } = {}) {
  const exports = {},
    components = {};
  const writes = [];
  const stub = (name) => (components[name] ||= Widget);
  new Function("require", "exports", source)((id) => {
    if (id === "swr")
      return {
        default: () => ({
          data: {
            id: "r",
            title: "记录A",
            name: "计划A",
            status: "draft",
            version: 5,
            edit_version: 3,
            workflow_version: 2,
          },
        }),
      };
    if (id === "./api") return { qualityApi: { write: async (...args) => writes.push(args) }, errorMessage: () => "" };
    if (id === "./types") return { can: () => true };
    if (id.startsWith("./")) return new Proxy({}, { get: (_, key) => (key === "fieldClass" ? "field" : stub(key)) });
    return require(id);
  }, exports);
  return {
    tree: exports.VersionRecordDialog({
      target: { kind, mode, id: mode === "create" ? undefined : "r" },
      base: "/q/",
      projectUrl: "/p/",
      build: "v9",
      context: { is_manager: manager },
      onClose() {},
      onSaved: async () => {},
    }),
    writes,
    components,
  };
}
test("点击需求状态直接渲染状态表单，不能混入删除提交回调", () => {
  const { tree, components } = dialog("requirement", "workflow");
  assert.equal(tree.type, components.RequirementState);
  assert.equal(tree.props.value.version, 5);
});
test("版本卡片新建三类记录均预填当前版本", () => {
  for (const kind of ["requirement", "plan", "defect"]) {
    const { tree } = dialog(kind, "create");
    assert.equal(kind === "requirement" ? tree.props.embedded.defaultBuild : tree.props.defaultBuild, "v9");
  }
});
test("删除与归档使用原版本号和原因，非经理不能提交", async () => {
  const { tree, writes } = dialog("requirement", "delete");
  const form = new FormData();
  form.set("reason", "重复录入");
  await tree.props.onSubmit(form);
  assert.deepEqual(writes, [
    ["/q/requirements/r/workflow/", { action: "trash", expected_version: 5, comment: "重复录入" }],
  ]);
  assert.equal(dialog("requirement", "delete", { manager: false }).tree.props.onSubmit, undefined);
});

function Widget() {}
