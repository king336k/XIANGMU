import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
function load(path) {
  const code = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const exports = {};
  new Function("require", "exports", code)((id) => {
    if (id === "next/navigation") return { useSearchParams: () => new URLSearchParams() };
    if (id === "@plane/constants") return { API_BASE_URL: "" };
    if (id === "@plane/ui") return { Button: (props) => React.createElement("button", props) };
    if (id === "swr") return { default: () => ({ data: { sources: [] } }) };
    if (id === "@/hooks/store/use-instance")
      return { useInstance: () => ({ config: { is_email_password_enabled: true } }) };
    if (id === "@/helpers/authentication.helper") return { authErrorHandler: () => undefined };
    return require(id);
  }, exports);
  return exports;
}
test("登录页同屏提供用户名和密码，不存在邮箱前置步骤", () => {
  const { UsernameLoginForm } = load("../core/components/account/username-login.tsx");
  const html = renderToStaticMarkup(React.createElement(UsernameLoginForm));
  assert.ok(html.includes('name="username"') && html.includes('name="password"'), html);
  assert.ok(html.includes('autoComplete="username"') && html.includes('autoComplete="current-password"'), html);
  assert.ok(!html.includes('type="email"'), html);
  assert.ok(html.includes('action="/api/quality-auth/login/"'), html);
  assert.ok(!html.includes("<select") && !html.includes("账号来源"), html);
});
test("日志阅读保留全文并转义代码，提供行号，换行模式不显示错位行号", () => {
  const { LogContent } = load("../core/components/quality/log-content.tsx");
  const text = "first\n<script>alert(1)</script>\nlast";
  const html = renderToStaticMarkup(React.createElement(LogContent, { text }));
  assert.ok(html.includes("1\n2\n3") && html.includes("last"), html);
  assert.ok(html.includes("&lt;script&gt;") && !html.includes("<script>"), html);
  const wrapped = renderToStaticMarkup(React.createElement(LogContent, { text, wrap: true }));
  assert.ok(!wrapped.includes('aria-hidden="true"'), wrapped);
});
