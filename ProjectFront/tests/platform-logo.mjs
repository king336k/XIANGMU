import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
test("品牌图支持明暗背景和紧凑图标，图片标明公司名称", () => {
  const code = ts.transpileModule(
    readFileSync(new URL("../core/components/common/platform-logo.tsx", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
  ).outputText;
  const exports = {};
  new Function("require", "exports", code)((id) => (id.endsWith("?url") ? { default: id } : require(id)), exports);
  for (const compact of [true, false]) {
    const html = renderToStaticMarkup(React.createElement(exports.PlatformLogo, { compact }));
    assert.ok(html.includes("忆生科技 TranscEngram"), html);
    assert.ok(!/Plane/.test(html), html);
    assert.ok(html.includes(compact ? "engram-symbol.png" : "engram-logo-light.png"), html);
  }
});
