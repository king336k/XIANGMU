import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const React = require("react");
const ts = require("typescript");
const Menu = Object.assign(() => null, { MenuItem: () => null });
function load() {
  const code = ts.transpileModule(
    readFileSync(new URL("../core/components/quality/statistics-display.tsx", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
  ).outputText;
  const exports = {};
  new Function("require", "exports", code)((id) => {
    if (id === "react") return { ...React, useState: (v) => [v, () => {}] };
    if (id === "@plane/ui") return { CustomMenu: Menu };
    if (id.startsWith("@plane/propel/charts/")) return {};
    return require(id);
  }, exports);
  return exports;
}
function nodes(tree, predicate) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap((x) => nodes(x, predicate));
  return [...(predicate(tree) ? [tree] : []), ...nodes(tree.props?.children, predicate)];
}
test("趋势展示菜单只显示趋势图、柱形图与数据表，切换只更改显示方式", () => {
  let result;
  const { StatisticsDisplay } = load();
  const tree = StatisticsDisplay({ value: "line", options: ["line", "bar", "table"], onChange: (v) => (result = v) });
  const options = nodes(tree, (n) => n.type === Menu.MenuItem);
  assert.equal(options.length, 3);
  options.find((n) => n.key === "table").props.onClick();
  assert.equal(result, "table");
});
test("分类下钻传递所点分类的真实键，零值不可下钻", () => {
  const { Distribution } = load();
  let result;
  const tree = Distribution({
    title: "测试结果",
    rows: [
      { key: "passed", name: "通过", count: 3, color: "#000" },
      { key: "failed", name: "失败", count: 1, color: "#111" },
      { key: "blocked", name: "阻塞", count: 0, color: "#222" },
    ],
    onSelect: (v) => (result = v),
  });
  const buttons = nodes(tree, (n) => n.type === "button");
  buttons.find((n) => n.key === "failed").props.onClick();
  assert.equal(result, "failed");
  assert.equal(buttons.find((n) => n.key === "blocked").props.disabled, true);
});
