import { AgentProcessingBadge } from "./agent-processing-fixture.js";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const source = readFileSync(new URL("../core/components/quality/record-presentation.tsx", import.meta.url), "utf8");
const code = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const exports = {};
new Function("require", "exports", code)(
  (id) =>
    id === "./agent-processing-badge"
      ? { AgentProcessingBadge }
      : id === "./table-header-filter"
        ? { TableHeaderFilter: ({ label }) => label }
        : id === "./record-badge"
          ? { Badge: ({ label, value }) => label || value }
          : require(id),
  exports
);
const { RecordPresentation } = exports;
const rows = [
  { id: "a", title: "DAQ-R-1 安全 <script>", status: "draft", statusName: "待完善", values: ["高", "v1"] },
  { id: "b", title: "DAQ-R-2 需求", status: "approved", statusName: "已确认", values: ["低", "v2"] },
];
function visit(node) {
  if (!node || typeof node !== "object") return;
  if (Array.isArray(node)) {
    node.forEach(visit);
    return;
  }
  if (node.type === "button") node.props.onClick();
  visit(node.props?.children);
}
test("列表、表格、看板保留同一组记录与转义", () => {
  for (const layout of ["list", "table", "board"]) {
    const html = renderToStaticMarkup(
      React.createElement(RecordPresentation, { rows, layout, columns: ["优先级", "版本"], onOpen: () => {} })
    );
    assert.ok(html.includes("DAQ-R-1") && html.includes("DAQ-R-2"));
    assert.ok(html.includes("&lt;script&gt;") && !html.includes("<script>"));
    if (layout === "table") assert.ok(html.includes("<table"));
    if (layout === "board")
      assert.ok(html.includes('aria-label="状态看板"') && html.includes("待完善") && html.includes("已确认"));
  }
});
test("布局切换只发起打开详情，不自行改变状态", () => {
  const clicked = [];
  const tree = RecordPresentation({
    rows,
    layout: "board",
    columns: ["优先级", "版本"],
    onOpen: (id) => clicked.push(id),
  });

  visit(tree);
  assert.deepEqual(clicked, ["a", "b"]);
  assert.equal(rows[0].status, "draft");
});
