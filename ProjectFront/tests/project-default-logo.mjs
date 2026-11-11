import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const logoPath = new URL("../../packages/propel/src/emoji-icon-picker/logo.tsx", import.meta.url);
const helperPath = new URL("../../packages/propel/src/emoji-icon-picker/helper.tsx", import.meta.url);
const lucidePath = new URL("../../packages/propel/src/emoji-icon-picker/lucide-icons.tsx", import.meta.url);

function load(file, fontLoaded) {
  const code = ts.transpileModule(readFileSync(file, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const exports = {};
  new Function("require", "exports", code)((id) => {
    if (id === "use-font-face-observer") return { default: () => fontLoaded };
    if (id === "./helper") return load(helperPath, fontLoaded);
    if (id === "./lucide-icons") return load(lucidePath, fontLoaded);
    return require(id);
  }, exports);
  return exports;
}

function render(props, fontLoaded = false) {
  return renderToStaticMarkup(React.createElement(load(logoPath, fontLoaded).Logo, props));
}

test("未配置或清空的项目图标使用可见文件夹 SVG，不显示空灰方块", () => {
  for (const logo of [
    undefined,
    {},
    { in_use: "" },
    { in_use: "icon", icon: {} },
    { in_use: "icon", icon: { name: " " } },
    { in_use: "emoji", emoji: { value: "" } },
  ]) {
    const html = render({ logo, size: 16 });
    assert.ok(html.includes("<svg") && html.includes("lucide-folder-kanban"), html);
    assert.ok(!html.includes("bg-layer-1"), html);
  }
});

test("Material 字体未加载时项目图标仍可见且装饰图标不抢读屏焦点", () => {
  const html = render({ logo: { in_use: "icon", icon: { name: "rocket_launch", color: "#e57a00" } }, size: 20 });
  assert.ok(html.includes("<svg"), html);
  assert.ok(html.includes('width="20"') && html.includes('height="20"'), html);
  assert.ok(html.includes('aria-hidden="true"') && html.includes('focusable="false"'), html);
});

test("已配置的项目 Emoji 保持原值", () => {
  const html = render({ logo: { in_use: "emoji", emoji: { value: "128640" } } });
  assert.ok(html.includes("🚀"), html);
  assert.ok(!html.includes("lucide-folder-kanban"), html);
});

test("Material 字体就绪后保留自定义图标与颜色", () => {
  const html = render({ logo: { in_use: "icon", icon: { name: "rocket_launch", color: "#e57a00" } } }, true);
  assert.ok(html.includes("material-symbols-rounded") && html.includes("rocket_launch"), html);
  assert.ok(html.includes("#e57a00"), html);
  assert.ok(!html.includes("lucide-folder-kanban"), html);
});

test("显式 Lucide 的视图图标保持原有实体和空值策略", () => {
  const html = render({ type: "lucide", logo: { in_use: "icon", icon: { name: "Activity", color: "#02b55c" } } });
  assert.ok(html.includes("lucide-activity") && html.includes("#02b55c"), html);
  assert.ok(render({ type: "lucide" }).includes("bg-layer-1"));
  assert.equal(render({ type: "lucide", logo: { in_use: "icon", icon: { name: "NoSuchViewIcon" } } }), "");
});
