import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
test("旧账号英文偏好不会使当前平台切回英文，读取资料不写原账号", async () => {
  const source = readFileSync(new URL("../core/store/user/profile.store.ts", import.meta.url), "utf8");
  const ast = ts.createSourceFile("profile.ts", source, ts.ScriptTarget.Latest, true);
  let initializer;
  function visit(node) {
    if (ts.isPropertyDeclaration(node) && node.name.getText(ast) === "fetchUserProfile") initializer = node.initializer;
    ts.forEachChild(node, visit);
  }
  visit(ast);
  const code = ts.transpileModule(`const fetchProfile=${initializer.getText(ast)};`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const calls = [],
    profile = { language: "en" },
    store = { userService: { getCurrentUserProfile: async () => profile } };
  const fetch = new Function("runInAction", "setLanguage", `${code}; return fetchProfile;`).call(
    store,
    (fn) => fn(),
    (language) => calls.push(language)
  );
  await fetch();
  assert.deepEqual(calls, ["zh-CN"]);
  assert.equal(profile.language, "en");
});
test("初始化不读取历史英文缓存，也不会因存储被禁用而失败", () => {
  const source = readFileSync(new URL("../../packages/i18n/src/core/instance.ts", import.meta.url), "utf8");
  assert.doesNotMatch(source, /localStorage.getItem\(LANGUAGE_STORAGE_KEY\)/);
});
