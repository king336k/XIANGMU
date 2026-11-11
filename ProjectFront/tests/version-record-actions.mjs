import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
function component() {
  const code = ts.transpileModule(
    readFileSync(new URL("../core/components/quality/version-records.tsx", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }
  ).outputText;
  const exports = {};
  new Function("require", "exports", code)((id) => {
    if (id === "./record-badge")
      return { Badge: ({ value, label }) => React.createElement("span", null, label || value) };
    if (id === "./types")
      return {
        can: (ctx, key) => ctx.capabilities[key],
        statusNames: { open: "待处理" },
        planStatusNames: { pending: "待分派" },
        defectDisplayTitle: (t) => t,
      };
    return require(id);
  }, exports);
  return exports.VersionRecords;
}
const version = {
  requirements: [{ id: "r", name: "需求A", status: "draft" }],
  tasks: [{ id: "t", name: "任务B", status: "待处理" }],
  plans: [{ id: "p", name: "计划C", status: "pending" }],
  defects: [{ id: "d", name: "缺陷D", status: "open" }],
};
test("版本四类卡片都有就地操作；需求可直接编辑，不依赖整行跳转", () => {
  const Record = component(),
    opened = [];
  const tree = Record({
    version,
    context: { capabilities: { knowledge_write: true, manage_test: true, report: true } },
    writable: true,
    finished: false,
    onOpen: (...args) => opened.push(args),
    onCreate() {},
    onLinkTask() {},
  });
  const html = renderToStaticMarkup(tree);
  for (const title of ["需求A", "任务B", "计划C", "缺陷D", "编辑需求", "查看 / 处理", "关联任务"])
    assert.ok(html.includes(title), title);
  visit(tree);
  assert.deepEqual(opened, [["requirement", "r", "edit"]]);
  assert.ok(!html.includes("<a "));
});
test("空卡片也有新建入口，已结束版本不显示新增按钮", () => {
  const Record = component(),
    empty = { requirements: [], tasks: [], plans: [], defects: [] };
  const props = {
    version: empty,
    context: { capabilities: { knowledge_write: true, manage_test: true, report: true } },
    writable: true,
    onOpen() {},
    onCreate() {},
    onLinkTask() {},
  };
  const active = renderToStaticMarkup(React.createElement(Record, props));
  assert.ok(active.includes("新建需求") && active.includes("新建计划") && active.includes("提交缺陷"));
  const ended = renderToStaticMarkup(React.createElement(Record, { ...props, finished: true }));
  assert.ok(!ended.includes("新建需求") && !ended.includes("关联任务"));
});

function visit(node) {
  if (!node || typeof node !== "object") return;
  if (Array.isArray(node)) {
    node.forEach(visit);
    return;
  }
  if (node.props?.["aria-label"] === "编辑需求：需求A") node.props.onClick({ stopPropagation() {} });
  visit(node.props?.children);
}
