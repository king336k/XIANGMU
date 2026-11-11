import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
function render(props) {
  const exports = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL("../core/components/home/personal-todos.tsx", import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((id) => {
    if (id === "react") return React;
    if (id === "swr") return { default: () => ({}) };
    if (id === "@/components/common/project-route-link")
      return { ProjectRouteLink: ({ to, children, ...p }) => React.createElement("a", { href: to, ...p }, children) };
    if (id === "@plane/utils") return { renderFormattedDate: (s) => s };
    if (id.endsWith("/record-badge")) return { Badge: ({ label, value }) => React.createElement("span", {"data-status":value}, label) };
    if (id.endsWith("/shared"))
      return { Paging: () => React.createElement("nav", { "aria-label": "分页" }), fieldClass: "field" };
    if (id.endsWith("/api")) return { qualityApi: {}, errorMessage: String };
    return require(id);
  }, exports);
  return renderToStaticMarkup(React.createElement(exports.PersonalTodoList, props));
}
const props = {
  rows: [
    {
      id: "d",
      kind: "defect",
      kind_name: "缺陷",
      title: "连接失败",
      code: "DEMO-D-1",
      status: "open",
      project_name: "演示项目",
      responsibility: "负责",
      next_action: "处理缺陷",
      url: "/demo/p/DEMO/defects/?defect=d",
      due_date: null,
    },
  ],
  count: 1,
  page: 1,
  perPage: 5,
  onPageChange() {},
  onPageSizeChange() {},
};
test("待办直接进入具体记录，显示职责下一步与中文状态", () => {
  const html = render(props);
  for (const s of ["DEMO-D-1", "连接失败", "负责", "处理缺陷", "待处理", "演示项目"]) assert.ok(html.includes(s), s);
  assert.match(html, /href="\/demo\/p\/DEMO\/defects\/\?defect=d"/);
  assert.match(html, /aria-label="分页"/);
  assert.doesNotMatch(html, /undefined|正确率/);
});
test("加载、失败、空结果明确且不同时显示旧数据", () => {
  assert.match(render({ ...props, rows: [], isLoading: true }), /正在读取待办/);
  const fail = render({ ...props, error: "读取失败" });
  assert.match(fail, /role="alert"/);
  assert.doesNotMatch(fail, /连接失败/);
  assert.match(render({ ...props, rows: [], count: 0 }), /暂无待办/);
});

test("工作项状态沿用语义色彩，原中文名称保持准确", () => {
  assert.match(render({...props,rows:[{...props.rows[0],kind:"task",status:"started"}]}), /data-status="in_progress"/);
});
