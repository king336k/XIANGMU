import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
function render(kind, is_administrator, outer = false) {
  const exports = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL(`../core/components/${kind}/settings/member-columns.tsx`, import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
    ).outputText
  )((id) => {
    if (id === "react/jsx-runtime") return require(id);
    if (id === "mobx-react") return { observer: (x) => x };
    if (id === "react-hook-form") return { useForm: () => ({ control: {}, formState: { errors: {} } }) };
    if (id === "@plane/constants")
      return {
        ROLE: { 20: "Admin", 15: "Member" },
        ROLE_DETAILS: { 20: { i18n_title: "管理员" }, 15: { i18n_title: "成员" }, 5: { i18n_title: "访客" } },
        EUserPermissions: { ADMIN: 20, GUEST: 5 },
        EUserPermissionsLevel: { WORKSPACE: "w" },
      };
    if (id === "@plane/i18n") return { useTranslation: () => ({ t: (x) => x }) };
    if (id === "@/hooks/store/use-member")
      return {
        useMember: () => ({
          project: { updateMemberRole() {} },
          workspace: { getWorkspaceMemberDetails: () => ({ role: 5 }), updateMember() {} },
        }),
      };
    if (id === "@/hooks/store/user")
      return {
        useUser: () => ({ data: { id: "viewer" } }),
        useUserPermissions: () => ({
          getProjectRoleByWorkspaceSlugAndProjectId: () => 5,
          allowPermissions: () => false,
        }),
      };
    return new Proxy({}, { get: () => () => null });
  }, exports);
  return renderToStaticMarkup(
    React.createElement(exports.AccountTypeColumn, {
      rowData: {
        is_administrator: outer ? is_administrator : undefined,
        member: { id: "target", is_administrator: outer ? undefined : is_administrator, is_active: true },
        role: 20,
        original_role: 20,
      },
      workspaceSlug: "w",
      projectId: "p",
    })
  );
}
test("native role20不伪称管理员，只有后端权威旗标显示管理员", () => {
  assert.match(render("project", false), /项目负责人/);
  assert.match(render("workspace", false), /工作空间负责人/);
  for (const kind of ["project", "workspace"]) {
    assert.match(render(kind, true), />管理员</);
    assert.doesNotMatch(render(kind, true), /负责人/);
  }
});

test("实际membership顶层旗标不会在成员列表渲染时丢失", () => {
  for (const kind of ["project", "workspace"]) assert.match(render(kind, true, true), />管理员</);
});
