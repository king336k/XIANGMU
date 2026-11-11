import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(import.meta.url),
  ts = require("typescript"),
  React = require("react");

function modal(hidden = []) {
  const exports = {},
    writes = [];
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/project/project-menu-settings.tsx", import.meta.url), "utf8"),
      {
        compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
      }
    ).outputText
  )(
    (name) =>
      name === "@/hooks/store/use-project"
        ? { useProject: () => ({ updateProject: async (...args) => writes.push(args) }) }
        : name === "@/components/quality/shared"
          ? { Modal: "modal" }
          : require(name),
    exports
  );
  const tree = exports.ProjectMenuSettings({
    workspaceSlug: "w",
    project: { id: "p", name: "项目甲", hidden_menu_items: hidden },
    onClose() {},
  });
  const nodes = (node) =>
    node && typeof node === "object" ? [node, ...React.Children.toArray(node.props?.children).flatMap(nodes)] : [];
  return { tree, writes, inputs: nodes(tree).filter((node) => node.type === "input") };
}

test("项目菜单弹窗提供六项复选，已隐藏测试反映为未勾选", () => {
  const h = modal(["quality"]);
  assert.equal(h.inputs.length, 6);
  assert.equal(h.inputs.find((node) => node.props.value === "quality").props.defaultChecked, false);
  assert.equal(h.inputs.find((node) => node.props.value === "defects").props.defaultChecked, true);
});

test("菜单设置仅保存本项目显示配置，不改变业务功能和权限", async () => {
  const h = modal();
  await h.tree.props.onSubmit({ getAll: () => ["requirements", "work_items", "defects", "versions", "knowledge"] });
  assert.deepEqual(h.writes, [["w", "p", { hidden_menu_items: ["quality"] }]]);
});

test("全部取消时阻止保存，保留至少一个入口", async () => {
  const h = modal();
  await assert.rejects(h.tree.props.onSubmit({ getAll: () => [] }), /至少保留/);
  assert.equal(h.writes.length, 0);
});
