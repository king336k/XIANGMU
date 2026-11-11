import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
function load() {
  const code = ts.transpileModule(
    readFileSync(new URL("../core/components/workspace/logo.tsx", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
  ).outputText;
  const exports = {};
  new Function("require", "exports", code)((id) => {
    if (id === "mobx-react") return { observer: (component) => component };
    if (id === "@plane/i18n") return { useTranslation: () => ({ t: () => "工作空间图标" }) };
    if (id === "@plane/utils") return { cn: (...args) => args.join(" "), getFileURL: (url) => url };
    return require(id);
  }, exports);
  return exports.WorkspaceLogo;
}
test("中文名和数字名的默认头像均用空间图标，不截取首字", () => {
  for (const name of ["中文体验工作区", "111", undefined]) {
    const html = renderToStaticMarkup(React.createElement(load(), { name }));
    assert.ok(html.includes("<svg"), html);
    assert.ok(html.includes("lucide-building2"), html);
    assert.ok(!html.includes(">中<") && !html.includes(">1<"), html);
  }
});
test("已上传的工作空间图标保持原图", () => {
  const html = renderToStaticMarkup(React.createElement(load(), { name: "自定义", logo: "/custom-logo.png" }));
  assert.ok(html.includes('src="/custom-logo.png"'));
});
