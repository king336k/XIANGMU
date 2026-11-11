import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const api = {};
new Function(
  "exports",
  ts.transpileModule(readFileSync(new URL("../core/components/quality/types.ts", import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS },
  }).outputText
)(api);
const context = (capabilities = {}, extra = {}) => ({
  can_write: true,
  business_roles_enabled: true,
  capabilities,
  ...extra,
});
test("知识维护、审核与全局模型配置分别按服务器权限显示", () => {
  const writer = context({ knowledge_write: true });
  const collector = context({ report: true, chat: true });
  const admin = context({ manage_roles: true }, { can_review_knowledge: true });
  for (const tab of ["editorial", "governance"]) {
    assert.equal(api.canOpenKnowledgeTab(writer, tab), true);
    assert.equal(api.canOpenKnowledgeTab(admin, tab), true);
    assert.equal(api.canOpenKnowledgeTab(collector, tab), false);
  }
  assert.equal(api.canOpenKnowledgeTab(admin, "settings"), false);
  assert.equal(api.canOpenKnowledgeTab(context({}, { can_configure_model: true }), "settings"), true);
  assert.equal(api.canOpenKnowledgeTab(collector, "search"), true);
});
test("成员与权限、平台集成不向非管理员显示，直接网址参数也同样拦截", () => {
  for (const tab of ["roles", "integrations"]) {
    assert.equal(api.canOpenQualityTab(context({ manage_roles: true }), tab), true);
    assert.equal(api.canOpenQualityTab(context({ report: true }), tab), false);
    assert.equal(api.canOpenQualityTab(context({ manage_roles: true }, { can_write: false }), tab), false);
    assert.equal(api.canOpenQualityTab(undefined, tab), false);
    assert.equal(api.canOpenQualityTab(context({}, { business_roles_enabled: false, is_manager: false }), tab), false);
    assert.equal(api.canOpenQualityTab(context({}, { business_roles_enabled: false, is_manager: true }), tab), true);
  }
  assert.equal(api.canOpenQualityTab(context({ report: true }), "plans"), true);
  assert.equal(api.canOpenKnowledgeTab(undefined, "editorial"), false);
});
