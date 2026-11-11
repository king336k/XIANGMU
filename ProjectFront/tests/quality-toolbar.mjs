import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const React = require("react");
const Menu = Object.assign(() => null, { MenuItem: () => null });
const Popover = Object.assign(() => null, { Button: () => null, Panel: () => null });
function load(name) {
  const code = ts.transpileModule(
    readFileSync(new URL(`../core/components/quality/${name}.tsx`, import.meta.url), "utf8"),
    {
      compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }
  ).outputText;
  const exports = {};
  new Function("require", "exports", code)((id) => {
    if (id === "react") return { ...React, useState: (value) => [value, () => {}] };
    if (id === "@plane/ui") return { CustomMenu: Menu, Button: "button" };
    if (id === "@plane/propel/popover") return { Popover };
    if (id === "./shared") return { fieldClass: "field" };
    if (id === "./saved-view-controls") return { SavedViewControls: () => null };
    if (id === "./defect-disposition") return { resolutionNames: {} };
    if (id === "./types")
      return { statusNames: { open: "待处理" }, planStatusNames: {}, severityNames: {}, priorityNames: {} };
    return require(id);
  }, exports);
  return exports;
}
function nodes(tree, predicate) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap((item) => nodes(item, predicate));
  return [...(predicate(tree) ? [tree] : []), ...nodes(tree.props?.children, predicate)];
}
test("视图格式放进单个下拉菜单，切换不丢失筛选、分页及个人视图", () => {
  const { LayoutControls } = load("layout-controls");
  const params = new URLSearchParams("tab=cases&search=上传&layout=list&page=2&saved_view=personal");
  let applied;
  const tree = LayoutControls({
    params,
    onApply: (next) => {
      applied = next;
    },
  });
  assert.equal(tree.type, Menu);
  const choices = nodes(tree, (node) => node.type === Menu.MenuItem);
  assert.equal(choices.length, 3);
  choices[2].props.onClick();
  assert.equal(applied.get("layout"), "board");
  for (const key of ["tab", "search", "page", "saved_view"]) assert.equal(applied.get(key), params.get(key));
});
test("紧凑筛选使用弹出层，条件数量排除导航和详情参数", () => {
  const { ListFilters } = load("list-filters");
  const tree = ListFilters({
    kind: "defects",
    context: { members: [] },
    params: new URLSearchParams("tab=defects&layout=board&defect=record&saved_view=mine&status=open"),
    onApply: () => {},
    compact: true,
  });
  assert.equal(nodes(tree, (node) => node.type === Popover).length, 1);
  const trigger = nodes(tree, (node) => node.type === Popover.Button)[0];
  assert.equal(trigger.props["aria-label"], "筛选，已应用1项条件");
});
test("清除条件保留页面与详情，取消已保存视图标记", () => {
  const { ListFilters } = load("list-filters");
  const params = new URLSearchParams(
    "tab=cases&layout=board&panel=list&defect=record&status=open&search=上传&page=4&saved_view=mine"
  );
  let applied;
  const tree = ListFilters({
    kind: "defects",
    context: { members: [] },
    params,
    onApply: (next) => {
      applied = next;
    },
    compact: true,
  });
  const clear = nodes(tree, (node) => node.props?.["aria-label"] === "清除全部筛选")[0];
  assert.ok(clear);
  clear.props.onClick();
  assert.deepEqual(Object.fromEntries(applied), { tab: "cases", layout: "board", panel: "list", defect: "record" });
});
