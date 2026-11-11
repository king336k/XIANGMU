import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
function helper() {
  const exports = {};
  new Function(
    "exports",
    ts.transpileModule(readFileSync(new URL("../core/components/profile/sidebar-width.ts", import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS },
    }).outputText
  )(exports);
  return exports;
}
test("右侧分隔线左拖变宽、右拖变窄，并为列表保留最小空间", () => {
  const { profileSidebarWidth } = helper();
  assert.equal(profileSidebarWidth(300, 900, 800, 1300), 400);
  assert.equal(profileSidebarWidth(300, 900, 1000, 1300), 240);
  assert.equal(profileSidebarWidth(300, 900, -1000, 1300), 440);
  assert.equal(profileSidebarWidth(300, 900, 800, 800), 320);
  assert.equal(profileSidebarWidth(NaN, 0, 0, 1300), 300);
});
test("个人栏可收起和键盘调宽，列表内容可以缩小且不用屏外占位", () => {
  const sidebar = readFileSync(new URL("../core/components/profile/sidebar.tsx", import.meta.url), "utf8");
  const layout = readFileSync(
    new URL("../app/(all)/[workspaceSlug]/(projects)/profile/[userId]/layout.tsx", import.meta.url),
    "utf8"
  );
  assert.ok(sidebar.includes("调整个人信息栏宽度") && sidebar.includes("aria-valuenow"));
  assert.ok(sidebar.includes("onPointerDown") && sidebar.includes("onKeyDown"));
  assert.doesNotMatch(sidebar, /marginLeft:.*window/);
  assert.ok(layout.includes("profile-workspace"));
});
