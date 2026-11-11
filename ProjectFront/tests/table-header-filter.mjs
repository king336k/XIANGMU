import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const React = require("react");
function load(params, onChange) {
  const code = ts.transpileModule(
    readFileSync(new URL("../core/components/quality/table-header-filter.tsx", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
  ).outputText;
  const exports = {};
  const Popover = Object.assign(() => null, { Button: () => null, Panel: () => null });
  new Function("require", "exports", code)(
    (id) =>
      id === "react"
        ? { ...React, useState: (v) => [v, () => {}] }
        : id === "react-router"
          ? { useSearchParams: () => [params, onChange] }
          : id === "@plane/propel/popover"
            ? { Popover }
            : id === "./paged-record-select"
              ? { PagedRecordSelect: () => null }
              : id === "./shared"
                ? { fieldClass: "field" }
                : id === "./types"
                  ? {
                      priorityNames: { high: "高" },
                      severityNames: { major: "严重" },
                      statusNames: { open: "待处理" },
                      planStatusNames: { running: "测试中" },
                      resultNames: { failed: "失败" },
                    }
                  : require(id),
    exports
  );
  return exports.TableHeaderFilter;
}
function nodes(tree, p) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap((x) => nodes(x, p));
  return [...(p(tree) ? [tree] : []), ...nodes(tree.props?.children, p)];
}
test("清除表头状态条件只删除状态，保留其他筛选及显示，重置分页和已保存视图", () => {
  let next;
  const Header = load(
    new URLSearchParams("status=open&search=上传&layout=table&page=4&saved_view=mine"),
    (value) => (next = value)
  );
  const tree = Header({ label: "状态", kind: "defects" });
  const clear = nodes(tree, (n) => n.type === "button" && n.props.type === "button")[0];
  clear.props.onClick();
  assert.deepEqual(Object.fromEntries(next), { search: "上传", layout: "table" });
});
test("不可筛选的操作列不显示无效按钮", () => {
  const Header = load(new URLSearchParams(), () => {});
  const tree = Header({ label: "操作", kind: "cases" });
  assert.equal(nodes(tree, (n) => n.props?.["aria-label"]).length, 0);
});
test("用例版本和执行版本采用不同筛选字段", () => {
  const Header = load(new URLSearchParams(), () => {});
  const cases = Header({ label: "版本", kind: "cases" });
  const executions = Header({ label: "版本", kind: "executions" });
  assert.equal(nodes(cases, (n) => n.type === "input")[0].props.name, "version");
  assert.equal(nodes(executions, (n) => n.type === "input")[0].props.name, "build");
});
