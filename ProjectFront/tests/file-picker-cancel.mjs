import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
function modal() {
  let closed = 0;
  const exports = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL("../core/components/quality/shared.tsx", import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((id) => {
    if (id === "react")
      return {
        ...React,
        useEffect: () => {},
        useId: () => "title",
        useRef: () => ({ current: null }),
        useState: (x) => [x, () => {}],
      };
    if (id === "react-dom") return { createPortal: (tree) => tree };
    if (id === "./api") return { errorMessage: String };
    if (id === "./pagination") return { PAGE_SIZES: [20, 50, 100], pageNumbers: () => [1] };
    if (id === "./record-badge") return {};
    if (id === "@plane/ui") return { Button: "button" };
    if (id === "lucide-react") return { X: "i", ChevronLeft: "i", ChevronRight: "i" };
    return require(id);
  }, exports);
  const old = globalThis.document;
  globalThis.document = { body: {} };
  try {
    return {
      tree: exports.Modal({ title: "提交缺陷", children: "draft", onClose: () => closed++ }),
      closed: () => closed,
    };
  } finally {
    globalThis.document = old;
  }
}
test("取消系统文件选择只结束选文件，不关闭缺陷/附件共用弹窗", () => {
  const h = modal(),
    dialog = {},
    input = { tagName: "INPUT", type: "file" };
  h.tree.props.onCancel({ target: input, currentTarget: dialog, preventDefault() {} });
  assert.equal(h.closed(), 0);
});
test("直接取消弹窗仍可正常关闭", () => {
  const h = modal(),
    dialog = {};
  h.tree.props.onCancel({ target: dialog, currentTarget: dialog, preventDefault() {} });
  assert.equal(h.closed(), 1);
});

test("关闭嵌套弹窗的取消事件不会关闭外层表单", () => {
  const parent = modal(),
    outer = {},
    inner = {};
  parent.tree.props.onCancel({ target: inner, currentTarget: outer, preventDefault() {} });
  assert.equal(parent.closed(), 0);
});
