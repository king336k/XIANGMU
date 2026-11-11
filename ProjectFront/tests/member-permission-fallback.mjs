import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
function load(path, mocks) {
  const api = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((id) => mocks[id] || (id === "react/jsx-runtime" ? require(id) : new Proxy({}, { get: () => () => null })), api);
  return api;
}
function roleCell(role) {
  const Controller = () => null;
  const mocks = {
    react: React,
    "mobx-react": { observer: (fn) => fn },
    "react-hook-form": { Controller, useForm: () => ({ control: {}, formState: { errors: {} } }) },
    "@plane/constants": {
      EUserPermissions: { ADMIN: 20, MEMBER: 15, GUEST: 5 },
      ROLE_DETAILS: { 15: { i18n_title: "member" } },
    },
    "@plane/i18n": { useTranslation: () => ({ t: (x) => x }) },
    "@/hooks/store/use-member": {
      useMember: () => ({
        project: { updateMemberRole() {} },
        workspace: { getWorkspaceMemberDetails: () => ({ role: 15 }) },
      }),
    },
    "@/hooks/store/user": {
      useUser: () => ({ data: { id: "actor" } }),
      useUserPermissions: () => ({ getProjectRoleByWorkspaceSlugAndProjectId: () => role }),
    },
  };
  const api = load("../core/components/project/settings/member-columns.tsx", mocks);
  return {
    tree: api.AccountTypeColumn({
      rowData: { member: { id: "other" }, original_role: 15 },
      workspaceSlug: "w",
      projectId: "p",
    }),
    Controller,
  };
}
test("未知或缺失项目角色按无管理权限处理，只有明确管理员可编辑他人权限", () => {
  for (const role of [undefined, 0, 7, 25, NaN, 5, 15]) {
    const r = roleCell(role);
    assert.notEqual(r.tree.props.children.type, r.Controller, `role=${role}`);
  }
  const admin = roleCell(20);
  assert.equal(admin.tree.props.children.type, admin.Controller);
});
test("原生成员选择器排除停用账号并保留正常成员与未指派选项", () => {
  const api = load("../core/components/project/member-select.tsx", {
    react: React,
    "mobx-react": { observer: (fn) => fn },
    "next/navigation": { useParams: () => ({ projectId: "p" }) },
    "@plane/types": { EUserProjectRoles: { GUEST: 5 } },
    "@/hooks/store/use-member": {
      useMember: () => ({
        project: {
          projectMemberIds: ["active", "inactive", "guest"],
          getProjectMemberDetails: (id) => ({
            role: id === "guest" ? 5 : 15,
            member: { id, display_name: id, is_active: id !== "inactive" },
          }),
        },
      }),
    },
    "@plane/utils": { getFileURL: () => "" },
  });
  const tree = api.MemberSelect({ value: "active", onChange() {} });
  assert.deepEqual(
    tree.props.options.map((x) => x.value),
    ["active", "none"]
  );
});
