import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
test("个人设置不再暴露访问令牌入口或页面，旧入口返回个人资料", () => {
  const exports = {};
  new Function(
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../../packages/constants/src/settings/profile.ts", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS } }
    ).outputText
  )(exports);
  assert.equal(exports.PROFILE_SETTINGS_TABS.includes("api-tokens"), false);
  assert.equal(exports.PROFILE_SETTINGS_CATEGORIES.includes(exports.PROFILE_SETTINGS_CATEGORY.DEVELOPER), false);
  const pages = readFileSync(
    new URL("../core/components/settings/profile/content/pages/index.ts", import.meta.url),
    "utf8"
  );
  assert.ok(!pages.includes('import("./api-tokens")'));
  const redirect = readFileSync(new URL("../app/routes/redirects/core/api-tokens.tsx", import.meta.url), "utf8");
  assert.ok(redirect.includes("/settings/profile/general/"));
});
test("登录外观保留品牌和用户名密码，绿色按钮不改统一登录调用", () => {
  const form = readFileSync(new URL("../core/components/account/username-login.tsx", import.meta.url), "utf8");
  assert.ok(form.includes('name="username"') && form.includes('name="password"'));
  assert.ok(form.includes("/api/quality-auth/login/") && form.includes("/auth/get-csrf-token/"));
  assert.ok(form.includes("!bg-[#16826c]"));
  const root = readFileSync(new URL("../core/components/account/auth-forms/auth-root.tsx", import.meta.url), "utf8");
  assert.ok(root.includes('aria-label="登录项目管理平台"'));
  assert.ok(root.includes("<PlatformLogo"));
});

test("登录边框使用当前项目可生成的色值，避免缺失调色板导致黑边", () => {
  for (const path of [
    "../core/components/account/auth-forms/auth-root.tsx",
    "../core/components/account/username-login.tsx",
  ]) {
    const text = readFileSync(new URL(path, import.meta.url), "utf8");
    assert.ok(!/border-emerald-|ring-emerald-|outline-emerald-/.test(text));
    assert.ok(/border-\[#(?:d7e4df|cbdad3)\]/.test(text));
  }
});
