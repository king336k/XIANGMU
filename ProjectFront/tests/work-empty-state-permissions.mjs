import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");

function renderEmptyState(file, arrange, filtered = false, projectIds = ["p"]) {
  const exports = {};
  const jsx = (type, props) => ({ type, props });
  const hooks = {
    "react/jsx-runtime": { jsx, jsxs: jsx },
    "react": { useState: () => [false, () => {}] },
    "lodash-es": { isEmpty: () => true },
    "mobx-react": { observer: (component) => component },
    "next/navigation": { useParams: () => ({ projectId: "p", cycleId: "c", moduleId: "m", workspaceSlug: "w" }) },
    "@plane/constants": { EUserPermissions: {}, EUserPermissionsLevel: {}, WORK_ITEM_TRACKER_ELEMENTS: { EMPTY_STATE_ADD_BUTTON: {} } },
    "@plane/types": { EUserProjectRoles: {}, EUserWorkspaceRoles: {}, EIssuesStoreType: {} },
    "@plane/i18n": { useTranslation: () => ({ t: (key) => key }) },
    "@plane/propel/empty-state": { EmptyStateDetailed: "EmptyStateDetailed" },
    "@plane/propel/toast": {},
    "@/hooks/store/use-command-palette": { useCommandPalette: () => ({ toggleCreateIssueModal() {} }) },
    "@/hooks/store/user": { useUserPermissions: () => ({ allowPermissions: () => true }) },
    "@/hooks/use-native-work-access": { useNativeWorkAccess: () => ({ canArrangeWork: () => arrange }) },
    "swr": { __esModule: true, default: () => ({ data: { can_create_workspace: arrange } }) },
    "@/components/quality/api": { qualityApi: {} },
    "@/hooks/store/use-project": { useProject: () => ({ workspaceProjectIds: projectIds }) },
    "@/hooks/store/work-item-filters/use-work-item-filter-instance": { useWorkItemFilterInstance: () => ({ hasActiveFilters: filtered }) },
    "@/hooks/store/use-cycle": { useCycle: () => ({ getCycleById: () => ({ status: "current" }) }) },
    "@/hooks/store/use-issues": { useIssues: () => ({ issues: {} }) },
    "@/components/core/modals/existing-issues-list-modal": { ExistingIssuesListModal: "ExistingIssuesListModal" },
  };
  const source = readFileSync(new URL(`../core/components/issues/issue-layouts/empty-states/${file}.tsx`, import.meta.url), "utf8");
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  new Function("require", "exports", js)((name) => {
    assert.ok(hooks[name], `unhandled import ${name}`);
    return hooks[name];
  }, exports);
  const nodes = [];
  function visit(node) {
    if (!node) return;
    if (Array.isArray(node)) return node.forEach(visit);
    if (node.type === "EmptyStateDetailed") nodes.push(node);
    visit(node.props?.children);
  }
  visit(Object.values(exports)[0]());
  return nodes.flatMap((node) => node.props.actions || []);
}

for (const file of ["project-issues", "cycle", "module"]) {
  test(`${file}只读成员仍可清除自己的筛选`, () => {
    const actions = renderEmptyState(file, false, true);
    assert.equal(actions.length, 1);
    assert.equal(actions[0].disabled, false);
  });
}

for (const file of ["project-issues", "project-view", "cycle", "module", "global-view"]) {
  test(`${file}的创建与添加入口遵守业务职责，不能只检查原生成员角色`, () => {
    const denied = renderEmptyState(file, false);
    assert.ok(denied.length > 0);
    assert.ok(denied.every((action) => action.disabled === true));
    assert.ok(renderEmptyState(file, true).every((action) => action.disabled === false));
  });
}

test("全局空工作空间的新建项目入口遵守服务器创建权限", () => {
  assert.equal(renderEmptyState("global-view", false, false, [])[0].disabled, true);
  assert.equal(renderEmptyState("global-view", true, false, [])[0].disabled, false);
});
