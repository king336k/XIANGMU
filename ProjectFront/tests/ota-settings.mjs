import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react"),
  { renderToStaticMarkup } = require("react-dom/server");
const source = readFileSync(new URL("../core/components/quality/connection-settings.tsx", import.meta.url), "utf8");
const Empty = () => null;
function render(editing = false, authorized = true, enabled = true) {
  let i = 0;
  const exports = {};
  const row = {
    source_instance: "field195",
    kind: "ota",
    base_url: "https://ota.example",
    portal_url: "https://ota.example/settings",
    roots: ["/home/operator/OTA", "/srv/升级包"],
    revision: 3,
    token_present: true,
  };
  new Function(
    "require",
    "exports",
    ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } })
      .outputText
  )(
    (name) =>
      name === "react"
        ? {
            ...React,
            useState: (init) => {
              const n = i++;
              return [editing && n === 0 ? row : n === 1 ? "ota" : init, () => {}];
            },
          }
        : name === "swr"
          ? {
              default: () => ({
                data: { can_configure: authorized, ota_directories_enabled: enabled, results: authorized ? [row] : [] },
                mutate() {},
              }),
            }
          : name === "@plane/ui"
            ? { Button: ({ children, ...props }) => React.createElement("button", props, children) }
            : name === "./shared"
              ? {
                  Field: ({ label, children }) => React.createElement("label", null, label, children),
                  Modal: ({ children }) => React.createElement("form", null, children),
                }
              : name.startsWith("./")
                ? new Proxy({}, { get: () => Empty })
                : require(name),
    exports
  );
  return renderToStaticMarkup(React.createElement(exports.ConnectionSettings, { base: "/quality/" }));
}
test("目录按实际配置逐行显示，外部入口仅打开明确地址，不显示凭据", () => {
  const html = render();
  assert.match(html, /当前安装包目录/);
  assert.match(html, /\/home\/operator\/OTA/);
  assert.match(html, /\/srv\/升级包/);
  assert.match(html, /打开外部部署平台/);
  assert.match(html, /rel="noopener noreferrer"/);
  assert.doesNotMatch(html, /安装成功|已发布|service_token.*value=/);
});
test("OTA编辑显示一行一个目录与仅保存边界，并提交roots和版本号", () => {
  const html = render(true);
  assert.match(html, /textarea[^>]*name="roots"/);
  assert.match(html, /\/home\/operator\/OTA\n\/srv\/升级包/);
  assert.doesNotMatch(html, /安装成功|已发布/);
  const helper = {};
  new Function(
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/quality/connection-form-data.ts", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }
    ).outputText
  )(helper);
  const form = new FormData();
  form.set("kind", "ota");
  form.set("base_url", "https://ota.example");
  form.set("roots", "/home/operator/OTA\n/srv/升级包");
  const payload = helper.connectionPayload(form, { source_instance: "field195", kind: "ota", revision: 3 }, true);
  assert.deepEqual(payload.roots, ["/home/operator/OTA", "/srv/升级包"]);
  assert.equal(payload.expected_revision, 3);
});
test("无管理员权限不显示配置入口或目录", () => {
  const html = render(false, false);
  assert.doesNotMatch(html, /添加连接|\/home\/operator\/OTA|打开外部部署平台/);
});

test("暂停的目录功能默认不展示", () => {
  const html = render(false, true, false);
  assert.doesNotMatch(html, /当前安装包目录|打开外部部署平台/);
});
