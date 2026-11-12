import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const React = require("react");
const stub = () => null;
const denied = () => null;
function load(path, editable) {
  const exp = {};
  const permission = { allowPermissions: () => editable };
  const imports = {
    react: { ...React, useMemo: (fn) => fn(), useState: (v) => [v, () => {}], useRef: () => ({ current: null }) },
    "react/jsx-runtime": require("react/jsx-runtime"),
    "mobx-react": { observer: (fn) => fn },
    swr: { default: () => ({}) },
    "next/navigation": { useParams: () => ({ workspaceSlug: "w", projectId: "p" }) },
    "@plane/constants": { EUserPermissions: { ADMIN: 20 }, EUserPermissionsLevel: { PROJECT: "PROJECT" } },
    "@plane/types": { EUserProjectRoles: { ADMIN: 20 } },
    "@plane/i18n": { useTranslation: () => ({ t: (key) => key }) },
    "@/hooks/store/user": { useUserPermissions: () => ({ allowPermissions: () => false }) },
    "@/components/settings/use-settings-permissions": { useSettingsPermissions: () => permission },
    "@/hooks/store/use-project-state": { useProjectState: () => ({ groupedProjectStates: {} }) },
    "@/hooks/store/use-label": { useLabel: () => ({ projectLabels: [], projectLabelsTree: [] }) },
  };
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(`../${path}`, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((id) => imports[id] || new Proxy({}, { get: () => stub }), exp);
  return exp;
}
function nodes(t) {
  return !t || typeof t !== "object" ? [] : Array.isArray(t) ? t.flatMap(nodes) : [t, ...nodes(t.props?.children)];
}
for (const editable of [true, false]) {
  test(`状态和标签设置按统一管理员权限呈现操作入口: ${editable}`, () => {
    const states = load("core/components/project-states/root.tsx", editable).ProjectStateRoot({
      workspaceSlug: "w",
      projectId: "p",
    });
    assert.equal(states.props.isEditable, editable);
    const labels = load("core/components/labels/project-setting-label-list.tsx", editable).ProjectSettingsLabelList();
    const heading = nodes(labels).find((n) => "control" in (n.props || {}));
    assert.equal(Boolean(heading.props.control), editable);
    const empty = nodes(labels).find((n) => "actions" in (n.props || {}));
    assert.equal(empty.props.actions.length > 0, editable);
  });
}

test("统一管理员可进入工作区事件通知配置，普通成员仍被拒绝", () => {
  const layoutPath = "app/(all)/[workspaceSlug]/(settings)/settings/(workspace)/layout.tsx";
  // Execute the route gate with a native-member admin; checking only the child page misses this boundary.
  for (const editable of [true, false]) {
    const exp = {};
    const imports = {
      "react/jsx-runtime": require("react/jsx-runtime"),
      "mobx-react": { observer: (fn) => fn },
      "next/navigation": { usePathname: () => "/w/settings/webhooks/" },
      "@plane/constants": {
        WORKSPACE_SETTINGS_ACCESS: { "/settings/webhooks": [20] },
        EUserPermissionsLevel: { WORKSPACE: "WORKSPACE" },
      },
      "@/hooks/store/user": {
        useUserPermissions: () => ({ workspaceUserInfo: {}, getWorkspaceRoleByWorkspaceSlug: () => 15 }),
      },
      "@/components/settings/use-settings-permissions": {
        useSettingsPermissions: () => ({ workspaceUserInfo: {}, allowPermissions: () => editable }),
      },
      "@/components/settings/helper": {
        pathnameToAccessKey: () => ({ accessKey: "/settings/webhooks" }),
        getWorkspaceActivePath: () => "",
      },
      "@/components/auth-screens/not-authorized-view": { NotAuthorizedView: denied },
    };
    new Function(
      "require",
      "exports",
      ts.transpileModule(readFileSync(new URL(`../${layoutPath}`, import.meta.url), "utf8"), {
        compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
      }).outputText
    )((id) => imports[id] || new Proxy({}, { get: () => () => null }), exp);
    const tree = exp.default({ params: { workspaceSlug: "w" } });
    assert.equal(
      nodes(tree).some((n) => n.type === denied),
      !editable
    );
  }
});

for (const manage of [true, false]) {
  test(`成员页按实际管理权限显示编辑入口: ${manage}`, () => {
    const exp = {};
    const imports = {
      react: { ...React, useState: (v) => [v, () => {}] },
      "react/jsx-runtime": require("react/jsx-runtime"),
      "mobx-react": { observer: (fn) => fn },
      swr: { default: () => ({ data: [], mutate() {} }), useSWRConfig: () => ({ mutate() {} }) },
      "@/hooks/store/user": { useUser: () => ({ data: { id: "viewer" } }) },
      "@/hooks/store/use-member": { useMember: () => ({ workspace: {} }) },
      "@/components/quality/types": { canOpenQualityTab: () => manage },
      "./member-management-data": {
        mergeMemberRows: () => [{ id: "person", username: "person", roles: [] }],
        DUTY_LABELS: {},
        accessUserId: () => "person",
        memberAccessLabel: () => "成员",
      },
    };
    new Function(
      "require",
      "exports",
      ts.transpileModule(
        readFileSync(new URL("../core/components/settings/unified-members.tsx", import.meta.url), "utf8"),
        {
          compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
        }
      ).outputText
    )((id) => imports[id] || new Proxy({}, { get: () => () => null }), exp);
    const tree = exp.UnifiedMembers({
      workspace: "w",
      projectId: "p",
      context: {},
      view: "project",
      onViewChange() {},
    });
    assert.equal(
      nodes(tree).some((n) => n.type === "button" && n.props.children === "编辑权限"),
      manage
    );
  });
}
