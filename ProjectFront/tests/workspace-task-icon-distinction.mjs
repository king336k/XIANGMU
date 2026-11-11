import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const base = new URL("../../packages/propel/src/icons/", import.meta.url);

function load(file) {
  const code = ts.transpileModule(readFileSync(file, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const exports = {};
  new Function("require", "exports", code)((id) => {
    if (id === "../icon-wrapper") return load(new URL("icon-wrapper.tsx", base));
    if (id === "@plane/propel/icons")
      return {
        WorkItemsIcon: load(new URL("project/work-items-icon.tsx", base)).WorkItemsIcon,
        ViewsIcon: load(new URL("project/view-icon.tsx", base)).ViewsIcon,
      };
    if (id === "@plane/utils") return { cn: (...values) => values.join(" ") };
    return require(id);
  }, exports);
  return exports;
}

test("需求与任务使用清单图标并保留调用者尺寸与颜色", () => {
  const Icon = load(new URL("project/work-items-icon.tsx", base)).WorkItemsIcon;
  const html = renderToStaticMarkup(
    React.createElement(Icon, { width: 14, height: 14, color: "#02b55c", "aria-hidden": true })
  );
  assert.ok(html.includes("lucide-list-checks"), html);
  assert.ok(html.includes('width="14"') && html.includes('height="14"'), html);
  assert.ok(html.includes("#02b55c") && html.includes('aria-hidden="true"'), html);
});

test("工作空间需求与任务聚合沿用相同工作项图标，不再借用视图叠层图标", () => {
  const helper = load(new URL("../core/components/workspace/sidebar/helper.tsx", import.meta.url));
  const html = renderToStaticMarkup(helper.getSidebarNavigationItemIcon("views"));
  assert.ok(html.includes("lucide-list-checks"), html);
  const source = readFileSync(
    new URL("../core/components/workspace/sidebar/workspace-menu.tsx", import.meta.url),
    "utf8"
  );
  const tree = ts.createSourceFile("workspace-menu.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let item;
  function visit(node) {
    if (
      ts.isObjectLiteralExpression(node) &&
      node.properties.some(
        (prop) =>
          ts.isPropertyAssignment(prop) &&
          prop.name.getText(tree) === "key" &&
          prop.initializer.getText(tree) === '"views"'
      )
    )
      item = node;
    ts.forEachChild(node, visit);
  }
  visit(tree);
  const icon = item.properties.find((prop) => ts.isPropertyAssignment(prop) && prop.name.getText(tree) === "Icon");
  assert.equal(icon.initializer.getText(tree), "WorkItemsIcon");
});

test("自定义视图图标仍使用原视图绘制，不被需求任务图标替换", () => {
  const Icon = load(new URL("project/view-icon.tsx", base)).ViewsIcon;
  const html = renderToStaticMarkup(React.createElement(Icon));
  assert.ok(html.includes("<path"), html);
  assert.ok(!html.includes("lucide-list-checks") && !html.includes("lucide-building2"), html);
});
