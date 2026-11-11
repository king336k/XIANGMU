import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
function columns(path, name) {
  const api = {};
  const mocks = {
    react: { ...React, useState: (value) => [value, () => {}] },
    swr: { default: () => ({ data: { members: {} } }) },
    "next/navigation": { useParams: () => ({ workspaceSlug: "w" }) },
    "@plane/constants": {
      EUserPermissions: { ADMIN: 20, GUEST: 5 },
      EUserPermissionsLevel: { PROJECT: "p", WORKSPACE: "w" },
    },
    "@plane/i18n": { useTranslation: () => ({ t: (key) => key }) },
    "@/hooks/store/user": {
      useUser: () => ({ data: { id: "u" } }),
      useUserPermissions: () => ({ allowPermissions: () => true, getProjectRoleByWorkspaceSlugAndProjectId: () => 20 }),
    },
    "@/hooks/store/use-member": {
      useMember: () => ({
        project: { filters: { getFilters: () => ({}), updateFilters() {} } },
        workspace: { filtersStore: { filters: {}, updateFilters() {} } },
      }),
    },
  };
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((id) => mocks[id] || (id === "react/jsx-runtime" ? require(id) : new Proxy({}, { get: () => () => null })), api);
  return api[name]({ projectId: "p", workspaceSlug: "w" }).columns;
}
test("项目成员仅保留账号、项目权限、加入日期，移除重复姓名昵称邮箱列", () => {
  const result = columns("../core/components/projects/settings/useProjectColumns.tsx", "useProjectColumns");
  assert.equal(result.length, 3);
  assert.equal(result[0].thRender().props.label, "账号");
  assert.equal(result[1].thRender().props.label, "项目权限");
});
test("工作区成员不再重复显示账号，保留项目职责和工作区权限", () => {
  const result = columns("../core/components/workspace/settings/useMemberColumns.tsx", "useMemberColumns");
  assert.equal(result[0].thRender().props.label, "账号");
  assert.equal(result.filter((x) => x.content === "账号").length, 0);
  assert.ok(result.some((x) => x.content === "项目职责"));
  assert.ok(result.some((x) => x.thRender?.().props.label === "工作空间权限"));
});
