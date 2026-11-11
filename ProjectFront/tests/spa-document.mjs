import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react"),
  { renderToStaticMarkup } = require("react-dom/server");
function layout() {
  const source = readFileSync(new URL("../app/root.tsx", import.meta.url), "utf8"),
    ast = ts.createSourceFile("root.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX),
    node = ast.statements.find((n) => ts.isFunctionDeclaration(n) && n.name?.text === "Layout");
  const code = ts.transpileModule(node.getText(ast).replace("export function", "function"), {
    compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const Child = () => null,
    Theme = ({ children }) => React.createElement("section", { "data-theme-provider": true }, children);
  return new Function(
    "React",
    "ThemeProvider",
    "Script",
    "Meta",
    "Links",
    "Scripts",
    "SITE_NAME",
    code + ";return Layout;"
  )(React, Theme, Child, Child, Child, Child, "项目管理平台");
}
test("静态外壳仅有一个应用容器，门户留在容器外且浏览器渲染不再嵌套html", () => {
  const previous = globalThis.window;
  delete globalThis.window;
  try {
    const Layout = layout(),
      server = renderToStaticMarkup(React.createElement(Layout, null, React.createElement("main", null, "loading")));
    assert.match(server, /id="platform-root"/);
    assert.match(server, /id="context-menu-portal"/);
    assert.equal((server.match(/<html/g) || []).length, 1);
    globalThis.window = {};
    const client = renderToStaticMarkup(React.createElement(Layout, null, React.createElement("main", null, "app")));
    assert.doesNotMatch(client, /<html|<head|<body|id="platform-root"/);
    assert.match(client, /<main>app<\/main>/);
    assert.match(client, /data-theme-provider/);
  } finally {
    if (previous === undefined) delete globalThis.window;
    else globalThis.window = previous;
  }
});
