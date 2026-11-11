import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
function load(path, user) {
  const exports = {};
  const code = ts.transpileModule(readFileSync(new URL(`../core/components/${path}.tsx`, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  new Function("require", "exports", code)((id) => {
    if (id === "@/components/home/user-greetings") return load("home/user-greetings", user);
    if (id === "react") return { ...React, useState: (value) => [value, () => {}] };
    if (id === "react/jsx-runtime") return require(id);
    if (id === "mobx-react") return { observer: (component) => component };
    if (id === "@/hooks/store/user") return { useUser: () => ({ data: user }) };
    if (id === "@/hooks/store/use-command-palette") return { useCommandPalette: () => ({}) };
    if (id === "@/hooks/use-current-time")
      return { useCurrentTime: () => ({ currentTime: new Date("2026-11-09T23:45:00Z") }) };
    if (id === "@plane/i18n")
      return {
        useTranslation: () => ({ t: (key) => ({ good: "", morning: "早上好", evening: "晚上好" })[key] || key }),
      };
    return new Proxy({}, { get: () => () => null });
  }, exports);
  return exports;
}
for (const path of ["home/user-greetings", "user/user-greetings"])
  test(`${path}以用户名问候并统一中国日期时间`, () => {
    const user = {
      username: "test-engineer",
      first_name: "过时名",
      last_name: "过时姓",
      user_timezone: "America/Los_Angeles",
    };
    const { UserGreetingsView } = load(path, user);
    const html = renderToStaticMarkup(React.createElement(UserGreetingsView, { user }));
    assert.ok(html.includes("test-engineer"));
    assert.ok(!html.includes("过时名"));
    assert.ok(html.includes("2026/11/10"));
    assert.ok(html.includes("07:45"));
    assert.ok(html.includes("早上好"));
  });
test("首次引导使用用户名，兼容尚未取到账号时显示中性问候", () => {
  for (const user of [{ username: "test-engineer", first_name: "旧名" }, undefined]) {
    const { TourRoot } = load("onboarding/tour/root", user);
    const html = renderToStaticMarkup(React.createElement(TourRoot, { onComplete() {} }));
    assert.ok(html.includes(user ? "你好，test-engineer" : "你好"));
    assert.ok(!html.includes("旧名"));
    assert.ok(!html.includes("你好， </h3>"));
  }
});
