import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
const stubs = new Map();
const stub = (key) => {
  if (!stubs.has(key)) stubs.set(key, () => null);
  return stubs.get(key);
};
const nodes = (tree) =>
  !tree || typeof tree !== "object"
    ? []
    : Array.isArray(tree)
      ? tree.flatMap(nodes)
      : [tree, ...nodes(tree.props?.children)];
const text = (tree) =>
  nodes(tree)
    .flatMap((n) => (Array.isArray(n.props?.children) ? n.props.children : [n.props?.children]))
    .filter((x) => typeof x === "string")
    .join(" ");
function load(file, task = true) {
  const out = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(`../core/components/issues/${file}.tsx`, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
    }).outputText
  )((id) => {
    if (id === "react/jsx-runtime") return require(id);
    if (id === "react") return { useState: (v) => [v, () => {}], useEffect() {} };
    if (id === "react-hook-form") return { useForm: () => ({ formState: { errors: {}, isSubmitting: false } }) };
    if (id === "@plane/utils") return { cn: (...v) => v.join(" ") };
    if (id === "mobx-react") return { observer: (x) => x };
    if (id === "next/navigation")
      return {
        useParams: () => ({ projectId: "p" }),
        usePathname: () => (typeof task === "string" ? task : task ? "/w/p/P/issues/" : "/w/p/P/quality/"),
      };

    if (id === "@plane/i18n")
      return {
        useTranslation: () => ({
          t: (key) =>
            ({
              "issue.new": "新建工作项",
              "epic.new": "新建史诗",
              "issue.add.label": "添加工作项",
              "project_empty_state.work_items.title": "还没有工作项",
              "project_empty_state.work_items.cta_primary": "新建工作项",
            })[key] || key,
        }),
      };
    if (id === "@/hooks/store/use-command-palette")
      return { useCommandPalette: () => ({ toggleCreateIssueModal: stub("toggle") }) };
    if (id === "@/hooks/use-native-work-access") return { useNativeWorkAccess: () => ({ canArrangeWork: () => true }) };
    if (id === "@/hooks/store/user") return { useUserPermissions: () => ({ allowPermissions: () => true }) };
    if (id.includes("use-work-item-filter-instance"))
      return { useWorkItemFilterInstance: () => ({ hasActiveFilters: false }) };
    if (id === "@plane/types")
      return {
        EIssuesStoreType: { PROJECT: "project", PROJECT_VIEW: "project-view" },
        EUserProjectRoles: { ADMIN: 20, MEMBER: 15 },
      };
    if (id === "@plane/constants") return { EUserPermissionsLevel: { PROJECT: "project" } };
    return new Proxy({}, { get: (_, key) => stub(key) });
  }, out);
  return out;
}
test("任务布局新建入口使用任务文案，Epic与其他页面保留原术语", () => {
  for (const [file, name] of [
    ["list", "ListQuickAddIssueButton"],
    ["kanban", "KanbanQuickAddIssueButton"],
    ["gantt", "GanttQuickAddIssueButton"],
    ["spreadsheet", "SpreadsheetAddIssueButton"],
  ]) {
    assert.match(
      text(load(`issue-layouts/quick-add/button/${file}`)[name]({ onClick() {}, label: "新建任务" })),
      /新建任务/
    );
    assert.doesNotMatch(
      text(load(`issue-layouts/quick-add/button/${file}`, false)[name]({ onClick() {} })),
      /新建任务/
    );
    assert.doesNotMatch(
      text(load(`issue-layouts/quick-add/button/${file}`)[name]({ onClick() {}, isEpic: true })),
      /新建任务/
    );
  }
});
test("任务空态创建入口与标题一致", () => {
  for (const [file, name] of [["project-issues", "ProjectEmptyState"]]) {
    const tree = load(`issue-layouts/empty-states/${file}`)[name]();
    const empty = nodes(tree).find((n) => n.props?.actions);
    assert.match(empty.props.title, /任务/);
    assert.equal(empty.props.actions[0].label, "新建任务");
  }
});
test("任务页面新建弹窗定向覆写标题和创建按钮，编辑草稿及外部自定义保留", () => {
  const modal = load("issue-modal/modal").CreateUpdateIssueModal;
  const props = { isOpen: true, onClose() {} };
  const create = nodes(modal(props)).find((n) => n.type === stub("CreateUpdateIssueModalBase"));
  assert.equal(create.props.modalTitle, "新建任务");
  assert.equal(create.props.primaryButtonText.default, "新建任务");
  for (const extra of [{ data: { id: "existing" } }, { isDraft: true }, { data: { is_epic: true } }]) {
    const tree = nodes(modal({ ...props, ...extra })).find((n) => n.type === stub("CreateUpdateIssueModalBase"));
    assert.equal(tree.props.modalTitle, undefined);
  }
  const custom = nodes(
    modal({ ...props, modalTitle: "专用创建", primaryButtonText: { default: "继续", loading: "处理中" } })
  ).find((n) => n.type === stub("CreateUpdateIssueModalBase"));
  assert.equal(custom.props.modalTitle, "专用创建");
  assert.equal(custom.props.primaryButtonText.default, "继续");
  const generic = nodes(load("issue-modal/modal", false).CreateUpdateIssueModal(props)).find(
    (n) => n.type === stub("CreateUpdateIssueModalBase")
  );
  assert.equal(generic.props.modalTitle, undefined);
});

test("任务页QuickAdd根组件按当前路由传递任务标签，其他项目视图保留工作项", () => {
  const task = load("issue-layouts/quick-add/root").QuickAddIssueRoot({
    layout: "list",
    QuickAddButton: stub("QuickAdd"),
  });
  assert.equal(nodes(task).find((n) => n.type === stub("QuickAdd")).props.label, "新建任务");
  const generic = load("issue-layouts/quick-add/root", false).QuickAddIssueRoot({
    layout: "list",
    QuickAddButton: stub("QuickAdd"),
  });
  assert.equal(nodes(generic).find((n) => n.type === stub("QuickAdd")).props.label, undefined);
  const epic = load("issue-layouts/quick-add/root").QuickAddIssueRoot({
    layout: "list",
    isEpic: true,
    QuickAddButton: stub("QuickAdd"),
  });
  assert.equal(nodes(epic).find((n) => n.type === stub("QuickAdd")).props.label, undefined);
});

test("短链接和旧项目任务列表命中，需求缺陷混合视图与详情不误标任务", () => {
  for (const path of ["/w/p/PROJ/issues", "/w/projects/project-uuid/issues/"]) {
    const tree = load("issue-layouts/quick-add/root", path).QuickAddIssueRoot({
      layout: "list",
      QuickAddButton: stub("QuickAdd"),
    });
    assert.equal(nodes(tree).find((n) => n.type === stub("QuickAdd")).props.label, "新建任务");
  }
  for (const path of [
    "/w/p/PROJ/views/v1/",
    "/w/p/PROJ/requirements/",
    "/w/p/PROJ/defects/",
    "/w/p/PROJ/issues/issue-id/",
    "/w/issues/",
  ]) {
    const tree = load("issue-layouts/quick-add/root", path).QuickAddIssueRoot({
      layout: "list",
      QuickAddButton: stub("QuickAdd"),
    });
    assert.equal(nodes(tree).find((n) => n.type === stub("QuickAdd")).props.label, undefined, path);
    const modal = load("issue-modal/modal", path).CreateUpdateIssueModal({ isOpen: true, onClose() {} });
    assert.equal(
      nodes(modal).find((n) => n.type === stub("CreateUpdateIssueModalBase")).props.modalTitle,
      undefined,
      path
    );
  }
});
