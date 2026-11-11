import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
function render(config) {
  const exports = {};
  const code = ts.transpileModule(
    readFileSync(new URL("../core/components/knowledge/model-settings.tsx", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
  ).outputText;
  new Function("require", "exports", code)(
    (id) =>
      id === "swr"
        ? { default: () => ({ data: config, mutate() {} }) }
        : id === "../quality/shared"
          ? { Field: ({ label, children }) => React.createElement("label", null, label, children), fieldClass: "field" }
          : id === "../quality/api"
            ? { qualityApi: {}, errorMessage: String }
            : id === "@plane/ui"
              ? { Button: ({ children, ...p }) => React.createElement("button", p, children) }
              : id === "./semantic-index-panel"
                ? { SemanticIndexPanel: () => null }
                : require(id),
    exports
  );
  return renderToStaticMarkup(React.createElement(exports.ModelSettings, { base: "/k/" }));
}
test("管理员日常配置聊天，内置检索只读且外部向量设置需显式进入高级选项", () => {
  const html = render({
    configured: true,
    key_present: true,
    model: "chat",
    base_url: "http://local",
    can_configure: true,
    semantic_enabled: true,
    embedding_model: "",
    semantic: { source: "builtin", managed: true, configured: true, status: "ready" },
  });
  assert.ok(!html.includes('name="semantic_enabled"'));
  assert.ok(!html.includes('name="embedding_model"'));
  assert.match(html, /内置知识检索 · 已就绪/);
  assert.match(html, /<details[^>]*>[\s\S]*高级设置：外部向量服务/);
  assert.match(html, /无需重复设置/);
  assert.doesNotMatch(html, /沿用问答模型/);
});
test("普通用户看不到可写语义配置", () => {
  const html = render({
    configured: true,
    key_present: true,
    model: "chat",
    base_url: "http://local",
    can_configure: false,
  });
  assert.ok(!html.includes('name="semantic_enabled"'));
  assert.ok(!html.includes('name="embedding_mode"'));
  assert.ok(!html.includes('name="api_key"'));
  assert.match(html, /修改模型配置请联系管理员/);
});
