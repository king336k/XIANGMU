import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const repoRoot = fileURLToPath(new URL("../../../../../", import.meta.url));
const requireWeb = createRequire(resolve(repoRoot, "ProjectFront/package.json"));
const ts = requireWeb("typescript");
const read = (path) => readFileSync(resolve(repoRoot, path), "utf8");
const dictionaries = Object.assign(
  {},
  ...readdirSync(resolve(repoRoot, "packages/i18n/src/locales/zh-CN"))
    .filter((file) => file.endsWith(".json"))
    .map((file) => JSON.parse(read(`packages/i18n/src/locales/zh-CN/${file}`)))
);
const translate = (key, variables = {}) => {
  const value = key.split(".").reduce((current, part) => current?.[part], dictionaries);
  assert.equal(typeof value, "string", `Missing Chinese key: ${key}`);
  return value.replace(/\{(\w+)\}/g, (_, name) => variables[name] ?? `{${name}}`);
};
const stub = new Proxy(function () {}, { get: () => stub });
function load(path, overrides = {}) {
  const output = ts.transpileModule(read(path), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    reportDiagnostics: true,
  });
  assert.equal(output.diagnostics.length, 0, path);
  const context = {
    exports: {},
    require: (name) => {
      if (overrides[name]) return overrides[name];
      if (name === "react/jsx-runtime")
        return {
          jsx: (type, props) => ({ type, props }),
          jsxs: (type, props) => ({ type, props }),
          Fragment: "fragment",
        };
      if (name === "react")
        return { useState: (value) => [value, () => {}], useRef: () => ({ current: null }), useEffect: () => {} };
      if (name === "mobx-react") return { observer: (component) => component };
      if (name === "swr") return { default: () => ({ data: undefined }) };
      if (name === "@plane/i18n") return { useTranslation: () => ({ t: translate }) };
      if (name === "@plane/constants")
        return {
          ROLE_DETAILS: { 20: { i18n_title: "role_details.admin.title" } },
          EIconSize: { XL: "xl" },
          STATE_TRACKER_ELEMENTS: {},
          PROJECT_TRACKER_ELEMENTS: {},
        };
      if (name === "@/hooks/store/user")
        return {
          useUserPermissions: () => ({
            getProjectRoleByWorkspaceSlugAndProjectId: () => 20,
            getWorkspaceRoleByWorkspaceSlug: () => 20,
          }),
        };
      if (name === "@/hooks/store/use-workspace")
        return { useWorkspace: () => ({ currentWorkspace: { slug: "demo", name: "User workspace" } }) };
      if (name === "@/hooks/store/use-project")
        return {
          useProject: () => ({
            getPartialProjectById: () => ({ name: "User project" }),
            joinedProjectIds: ["project"],
            getProjectById: () => ({ name: "User project" }),
          }),
        };
      if (name === "@/hooks/use-app-router") return { useAppRouter: () => ({ push: () => {} }) };
      if (name === "@plane/utils")
        return {
          cn: (...values) => values.filter((value) => typeof value === "string").join(" "),
          joinUrlPath: (...values) => values.join("/"),
        };
      return stub;
    },
  };
  vm.runInNewContext(output.outputText, context);
  return context.exports;
}
function texts(node) {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(texts).join(" ");
  if (!node) return "";
  return texts(node.props?.children);
}

test("settings sidebar titles render in Chinese while preserving user names", () => {
  for (const [area, exportName, title, userName] of [
    ["project", "ProjectSettingsSidebarHeader", "项目设置", "User project"],
    ["workspace", "WorkspaceSettingsSidebarHeader", "设置", "User workspace"],
  ]) {
    const component = load(`ProjectFront/core/components/settings/${area}/sidebar/header.tsx`)[exportName];
    const rendered = texts(component({ projectId: "project" }));
    assert.ok(rendered.includes(title), rendered);
    assert.ok(rendered.includes(userName), rendered);
  }
});

test("all built-in state groups render Chinese names without changing action payload keys", () => {
  const { GroupItem } = load("ProjectFront/core/components/project-states/group-item.tsx");
  for (const groupKey of ["backlog", "unstarted", "started", "completed", "cancelled"]) {
    const expanded = [];
    const tree = GroupItem({
      groupKey,
      groupedStates: {},
      states: [],
      groupsExpanded: [groupKey],
      isEditable: true,
      stateOperationsCallbacks: {},
      handleExpand: (key) => expanded.push(key),
    });
    const rendered = texts(tree);
    assert.ok(rendered.includes(translate(`filters_workspace.state_groups.${groupKey}`)), rendered);
    assert.ok(!rendered.includes(groupKey), rendered);
    const addButton = tree.props.children[0].props.children[1];
    addButton.props.onClick();
    assert.equal(expanded[0], groupKey);
  }
});

test("project feature toggle renders Chinese status and retains feature property", () => {
  const { ProjectFeatureToggle } = load("ProjectFront/core/components/project/settings/helper.tsx");
  for (const [value, label] of [
    [true, "已启用"],
    [false, "已禁用"],
  ]) {
    const tree = ProjectFeatureToggle({
      workspaceSlug: "demo",
      projectId: "project",
      featureItem: { href: "cycles", key: "cycles", property: "cycle_view" },
      value,
    });
    assert.ok(texts(tree).includes(label));
  }
  let payload;
  const tree = ProjectFeatureToggle({
    featureItem: { key: "cycles", property: "cycle_view" },
    value: true,
    handleSubmit: (...values) => {
      payload = values;
    },
  });
  tree.props.onChange();
  assert.deepEqual(payload, ["cycles", "cycle_view"]);
});

test("archive modal renders Chinese confirmation and keeps the project name", () => {
  const { ArchiveRestoreProjectModal } = load("ProjectFront/core/components/project/archive-restore-modal.tsx");
  for (const [archive, label] of [
    [true, "归档"],
    [false, "恢复"],
  ]) {
    const rendered = texts(
      ArchiveRestoreProjectModal({ workspaceSlug: "demo", projectId: "project", isOpen: true, archive })
    );
    assert.ok(rendered.includes(label), rendered);
    assert.ok(rendered.includes("User project"), rendered);
    assert.ok(rendered.includes("取消"), rendered);
    assert.ok(!/Archive|Restore|Cancel/.test(rendered), rendered);
  }
});

test("state creation keeps API group values and response statuses while localizing feedback", async () => {
  const toasts = [];
  const { StateCreate } = load("ProjectFront/core/components/project-states/create-update/create.tsx", {
    "@plane/constants": { STATE_GROUPS: { started: { color: "#000000" } } },
    "@plane/propel/toast": { TOAST_TYPE: { SUCCESS: "success" }, setToast: (toast) => toasts.push(toast) },
  });
  let payload;
  const tree = StateCreate({
    groupKey: "started",
    createStateCallback: async (value) => {
      payload = value;
    },
    handleClose: () => {},
  });
  assert.equal(tree.props.buttonTitle, "创建");
  const result = await tree.props.onSubmit({ name: "User state", description: "User description" });
  assert.equal(result.status, "success");
  assert.equal(payload.group, "started");
  assert.equal(payload.name, "User state");
  assert.equal(payload.description, "User description");
  assert.equal(toasts[0].message, "状态创建成功。");
});

test("project feature settings keep API field names and boolean payloads", async () => {
  let payload;
  let feedback;
  const { ProjectSettingsFeatureControlItem } = load(
    "ProjectFront/core/components/settings/project/content/feature-control-item.tsx",
    {
      "@/hooks/store/use-project": {
        useProject: () => ({
          getProjectById: () => ({ cycle_view: true }),
          updateProject: async (...values) => {
            payload = values;
          },
        }),
      },
      "@plane/propel/toast": {
        setPromiseToast: (_promise, toast) => {
          feedback = toast;
        },
      },
    }
  );
  const tree = ProjectSettingsFeatureControlItem({
    workspaceSlug: "demo",
    projectId: "project",
    featureProperty: "cycle_view",
    value: true,
  });
  tree.props.control.props.onChange();
  assert.deepEqual(payload.slice(0, 2), ["demo", "project"]);
  assert.deepEqual(Object.keys(payload[2]), ["cycle_view"]);
  assert.equal(payload[2].cycle_view, false);
  assert.equal(feedback.success.message(), "项目功能更新成功。");
  assert.equal(feedback.error.message(), "项目功能更新失败，请重试。");
  await Promise.resolve();
});

test("built-in state names display Chinese while custom names and state objects remain unchanged", () => {
  const { StateItemTitle } = load("ProjectFront/core/components/project-states/state-item-title.tsx", {
    "@/hooks/store/use-project-state": { useProjectState: () => ({ getStatePercentageInGroup: () => 100 }) },
  });
  for (const [group, name, label] of [
    ["backlog", "Backlog", "待排期"],
    ["unstarted", "Todo", "待开始"],
    ["started", "In Progress", "进行中"],
    ["completed", "Done", "已完成"],
    ["cancelled", "Cancelled", "已取消"],
    ["started", "User state", "User state"],
    ["started", "Done", "Done"],
  ]) {
    const state = Object.freeze({ id: "state", group, name, description: "User description" });
    const rendered = texts(StateItemTitle({ state, stateCount: 1, disabled: true }));
    assert.ok(rendered.includes(label), rendered);
    assert.ok(rendered.includes("User description"), rendered);
    assert.equal(state.name, name);
  }
});

test("estimate deletion renders Chinese and keeps user-provided estimate names", () => {
  const { DeleteEstimateModal } = load("ProjectFront/core/components/estimates/delete/modal.tsx", {
    "@/hooks/store/estimates": { useProjectEstimates: () => ({}) },
    "@/hooks/store/estimates/use-estimate": { useEstimate: () => ({ asJson: { name: "User estimate" } }) },
  });
  const rendered = texts(DeleteEstimateModal({ isOpen: true }));
  assert.ok(rendered.includes("删除估点"), rendered);
  assert.ok(rendered.includes("User estimate"), rendered);
  assert.ok(rendered.includes("取消"), rendered);
  assert.ok(!/Deleting|Delete Estimate|Cancel/.test(rendered), rendered);
});

test("work item draft confirmation renders Chinese and keeps all action handlers", async () => {
  let discarded = 0;
  let confirmed = 0;
  let closed = 0;
  const { ConfirmIssueDiscard } = load("ProjectFront/core/components/issues/confirm-issue-discard.tsx");
  const tree = ConfirmIssueDiscard({
    isOpen: true,
    onDiscard: () => discarded++,
    onConfirm: async () => confirmed++,
    handleClose: () => closed++,
  });
  const rendered = texts(tree);
  for (const label of ["保存此草稿", "放弃", "取消", "保存到草稿"]) assert.ok(rendered.includes(label), rendered);
  const buttons = [];
  const visit = (node) => {
    if (Array.isArray(node)) return node.forEach(visit);
    if (!node?.props) return;
    if (node.props.onClick) buttons.push(node);
    visit(node.props.children);
  };
  visit(tree);
  buttons[0].props.onClick();
  buttons[1].props.onClick();
  await buttons[2].props.onClick();
  assert.equal(discarded, 1);
  assert.equal(closed, 1);
  assert.equal(confirmed, 1);
});

test("work item history localizes the sentence while preserving operation verbs and user source", () => {
  const { IssueDefaultActivity } = load(
    "ProjectFront/core/components/issues/issue-detail/issue-activity/activity/actions/default.tsx",
    {
      "@plane/types": { EInboxIssueSource: { IN_APP: "in-app" } },
      "@plane/utils": { capitalizeFirstLetter: (value) => value },
      "@/hooks/store/use-issue-detail": {
        useIssueDetail: () => ({
          activity: { getActivityById: () => ({ verb: "created", source_data: { source: "user-integration" } }) },
        }),
      },
    }
  );
  const rendered = texts(IssueDefaultActivity({ activityId: "activity" }));
  assert.ok(rendered.includes("创建了工作项"), rendered);
  assert.ok(rendered.includes("user-integration"), rendered);
  assert.ok(!rendered.includes("deleted"), rendered);
});

test("项目设置头部采用服务器业务岗位，不把native20的项目经理显示为管理员", () => {
  const { ProjectSettingsSidebarHeader } = load("ProjectFront/core/components/settings/project/sidebar/header.tsx", {
    swr: { default: () => ({ data: { business_role_name: "项目经理" } }) },
    "@/components/quality/duty-summary": { projectDutySummary: (roles) => ({ label: roles.join("、") }) },
  });
  const rendered = texts(ProjectSettingsSidebarHeader({ projectId: "project" }));
  assert.match(rendered, /项目经理/);
  assert.doesNotMatch(rendered, /管理员/);
});
