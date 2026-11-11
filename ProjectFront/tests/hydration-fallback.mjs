import assert from "node:assert/strict";
import fs from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const React = require("react");
const { renderToString } = require("react-dom/server");
const source = fs.readFileSync(new URL("../app/root.tsx", import.meta.url), "utf8");
const ast = ts.createSourceFile("root.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const node = ast.statements.find((n) => ts.isFunctionDeclaration(n) && n.name?.text === "HydrateFallback");
assert.ok(node, "Root must expose a hydration fallback");
const code = ts.transpileModule(node.getText(ast).replace("export function", "function"), {
  compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2022 },
}).outputText;
const fallback = new Function("React", "useTheme", "LogoSpinner", code + ";return HydrateFallback;")(
  React,
  () => ({ resolvedTheme: "light" }),
  () => React.createElement("span", null, "loading")
);
delete globalThis.window;
const server = renderToString(React.createElement(fallback));
globalThis.window = {};
const browser = renderToString(React.createElement(fallback));
delete globalThis.window;
assert.equal(browser, server, "First browser render must match static hydration markup");
console.log("Hydration fallback server/client markup matches.");
