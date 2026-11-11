import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
test("通知选项使用原生按钮，保留点击回调与可读文本", () => {
  const api = {},
    handler = () => {};
  const code = ts.transpileModule(
    readFileSync(
      new URL(
        "../core/components/workspace-notifications/sidebar/header/options/menu-option/menu-item.tsx",
        import.meta.url
      ),
      "utf8"
    ),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
  ).outputText;
  new Function("require", "exports", code)(
    (id) =>
      id === "mobx-react" ? { observer: (fn) => fn } : id === "@plane/utils" ? { cn: (value) => value } : require(id),
    api
  );
  const tree = api.NotificationMenuOptionItem({ type: "menu-item", label: "全部标为已读", onClick: handler });
  assert.equal(tree.type, "button");
  assert.equal(tree.props.type, "button");
  assert.equal(tree.props.onClick, handler);
  assert.equal(tree.props.children[1].props.children, "全部标为已读");
});
