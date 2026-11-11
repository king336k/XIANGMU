import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(import.meta.url),
  ts = require("typescript");
function dialog(name = "项目甲", maxLength = 255) {
  const exports = {},
    writes = [];
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL("../core/components/common/rename-dialog.tsx", import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )(
    (id) =>
      id === "@/components/quality/shared" ? { Modal: "modal", Field: "field", fieldClass: "field" } : require(id),
    exports
  );
  return {
    tree: exports.RenameDialog({
      title: "重命名项目",
      label: "项目名称",
      name,
      maxLength,
      onClose() {},
      onRename: async (value) => writes.push(value),
    }),
    writes,
  };
}
test("重命名只提交修剪后的名称，不变和空白不触发写入", async () => {
  const h = dialog();
  await h.tree.props.onSubmit({ get: () => "  新项目名称  " });
  assert.deepEqual(h.writes, ["新项目名称"]);
  const same = dialog();
  await same.tree.props.onSubmit({ get: () => " 项目甲 " });
  assert.deepEqual(same.writes, []);
  await assert.rejects(same.tree.props.onSubmit({ get: () => "   " }), /名称/);
  assert.deepEqual(same.writes, []);
});
test("工作区名称长度与项目名称长度分别保留服务端限制", async () => {
  const h = dialog("工作区", 80);
  await assert.rejects(h.tree.props.onSubmit({ get: () => "字".repeat(81) }), /80/);
  assert.deepEqual(h.writes, []);
});
test("保存失败保留弹窗，由统一弹窗处理错误", async () => {
  const h = dialog();
  h.writes.push = () => {
    throw Error("保存失败");
  };
  await assert.rejects(h.tree.props.onSubmit({ get: () => "新名字" }), /保存失败/);
});
test("工作区与项目菜单提供重命名入口并保留名称外的标识", () => {
  for (const path of ["workspace/sidebar/workspace-menu-root.tsx", "workspace/sidebar/projects-list-item.tsx"]) {
    const source = readFileSync(new URL(`../core/components/${path}`, import.meta.url), "utf8");
    assert.match(source, /RenameDialog/);
    assert.match(source, /重命名/);
    assert.match(source, /\{ name \}/);
  }
});
