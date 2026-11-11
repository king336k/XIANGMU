import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
const stubs = new Map();
const stub = (n) => {
  if (!stubs.has(n)) stubs.set(n, () => null);
  return stubs.get(n);
};
const tester = {
  user_id: "tester",
  is_manager: false,
  business_role: "REGRESSION_TESTER",
  business_roles: ["REGRESSION_TESTER"],
  business_role_name: "测试员",
  business_roles_enabled: true,
  can_write: true,
  identifier: "P",
  members: [],
  capabilities: { manage_case: true, manage_test_plan: true, execute: true, manage_test: false },
};
function load(file, context = tester, tab = "cases", collection = []) {
  const exp = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(`../core/components/quality/${file}.tsx`, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((id) => {
    if (id === "react")
      return {
        ...React,
        useState: (v) => [typeof v === "function" ? v() : v, () => {}],
        useEffect() {},
        useMemo: (f) => f(),
      };
    if (id === "react/jsx-runtime") return require(id);
    if (id === "swr")
      return {
        default: (url) => ({
          data: url?.includes("context/")
            ? context
            : url?.includes("report/")
              ? undefined
              : url?.includes("data-regressions/")
                ? []
                : url?.includes("test-resources/")
                  ? { ready: true, resources: [], errors: [] }
                  : url?.includes("all")
                    ? []
                    : { results: collection, count: collection.length },
          mutate: async () => {},
          isLoading: false,
        }),
        useSWRConfig: () => ({ mutate: async () => {} }),
      };
    if (id === "./use-collection-pagination")
      return {
        useCollectionPagination: () => ({
          rows: [{ id: "r", name: "测试服务器", kind: "server", status: "available" }],
          paging: {},
        }),
      };
    if (id === "react-router")
      return {
        useLocation: () => ({ hash: "" }),
        useSearchParams: () => [new URLSearchParams(`tab=${tab}&layout=list`), () => {}],
        useParams: () => ({ projectId: "P" }),
      };
    if (id === "@/hooks/use-resolved-project-params")
      return { useResolvedProjectParams: () => ({ workspaceSlug: "w", projectId: "p" }) };
    if (id === "./pagination") return { normalizedPageParams: (p) => p, pageSize: () => 50 };
    if (id === "./layout-controls") return { recordLayout: () => "list" };
    if (id === "./types")
      return {
        can: (c, key) => c.can_write && (!c.business_roles_enabled || c.capabilities[key] === true),
        canOpenQualityTab: () => true,
        planStatusNames: {},
        priorityNames: {},
        severityNames: {},
        resultNames: {},
        statusNames: {},
        reasonNames: {},
        defectDisplayTitle: (x) => x,
      };
    if (id === "./duty-summary") return { projectDutySummary: () => ({ label: "测试员" }) };
    if (id === "./api") return { qualityApi: {}, errorMessage: String };
    return new Proxy({}, { get: (_, key) => (key === "fieldClass" ? "field" : stub(key)) });
  }, exp);
  return exp;
}
const nodes = (t) =>
  !t || typeof t !== "object" ? [] : Array.isArray(t) ? t.flatMap(nodes) : [t, ...nodes(t.props?.children)];
const labels = (t) =>
  nodes(t)
    .filter((n) => n.type === stub("Button"))
    .map((n) =>
      [n.props.children]
        .flat()
        .filter((v) => typeof v === "string")
        .join("")
    );
const plan = {
  id: "p1",
  name: "计划",
  build: "v1",
  environment: "验收",
  items: [],
  summary: { executed: 0, total: 1, passed: 1, inconclusive: 0 },
  status: "pending",
  workflow_version: 1,
  workflow_events: [],
  round_no: 1,
  assignee_id: "other",
  data_regression: null,
};
const suite = {
  id: "s",
  name: "套件",
  description: "",
  published: false,
  archived_at: null,
  trashed_at: null,
  edit_version: 1,
  items: [],
};
test("测试员能维护和复制计划、分派负责人，但不能经理确认或退回", () => {
  assert.ok(
    load("plan-actions").PlanActions({ base: "/q/", plan, context: tester, onSaved: async () => {}, onCopied() {} })
  );
  const form = load("plan-form").PlanForm({ base: "/q/", context: tester, onSaved: async () => {} });
  assert.equal(nodes(form).find((n) => n.type === "select" && n.props.name === "assignee_id").props.disabled, false);
  const workflow = load("workflow-panel").PlanWorkflowPanel;
  const args = { base: "/q/", context: tester, onSaved: async () => {} };
  assert.ok(labels(workflow({ ...args, plan })).includes("分派负责人"));
  assert.ok(labels(workflow({ ...args, plan })).includes("取消计划"));
  assert.ok(
    !labels(workflow({ ...args, plan: { ...plan, status: "review" } })).some((x) =>
      ["确认测试结果", "退回复测"].includes(x)
    )
  );
});
test("测试员能新建编辑复制归档发布测试套件，不能创建或确认项目发布检查", () => {
  const Assets = load("assets-panel").AssetsPanel;
  const args = { base: "/q/", context: tester, onSaved: async () => {} };
  const tree = Assets({ ...args, kind: "suites", rows: [suite] });
  for (const text of ["新建用例集", "编辑草稿", "复制为新草稿", "发布用例集"])
    assert.ok(labels(tree).includes(text), text);
  assert.ok(nodes(tree).some((n) => n.type === stub("RecordLifecycleActions")));
  const release = {
    id: "r",
    name: "发布",
    version: "v1",
    status: "draft",
    readiness: { ready: true, plans: [], blockers: [] },
  };
  assert.ok(
    !labels(Assets({ ...args, kind: "releases", rows: [release] })).some((x) =>
      ["新建发布检查", "确认发布检查", "编辑发布计划"].includes(x)
    )
  );
});
test("用例和计划顶部创建导入入口按独立能力开放，不改变其他岗位", () => {
  for (const tab of ["cases", "plans"]) {
    const tree = load("workbench", tester, tab).QualityWorkbench({});
    for (const text of tab === "cases" ? ["新建用例", "导入用例"] : ["新建计划", "导入任务包"])
      assert.ok(labels(tree).includes(text), text);
    const reporter = { ...tester, business_role: "REPORTER", capabilities: { report: true } };
    assert.ok(
      !labels(load("workbench", reporter, tab).QualityWorkbench({})).includes(tab === "cases" ? "新建用例" : "新建计划")
    );
  }
});
test("测试员可登记测试执行资源与选择计划资源，能力缺失不能借经理标记绕过", () => {
  const tree = load("test-resources-panel").TestResourcesPanel({ base: "/q/", context: tester });
  assert.ok(labels(tree).includes("登记测试资源"));
});

test("用例列表编辑复制和生命周期由manage_case授权，而非经理标签", () => {
  const value = { id: "c", title: "测试用例", steps: [], priority: "medium", version: 1 };
  const tree = load("workbench", tester, "cases", [value]).QualityWorkbench({});
  const list = nodes(tree).find((n) => n.type === stub("CaseList"));
  assert.equal(list.props.canWrite, true);
  assert.equal(typeof list.props.onSelection, "function");
  const bulk = nodes(tree).find((n) => n.type === stub("BulkActionsBar"));
  assert.ok(bulk);
  const denied = { ...tester, can_write: false };
  assert.equal(labels(load("workbench", denied, "cases").QualityWorkbench({})).includes("新建用例"), false);
});

test("经理样式标记不能替代明确验收能力，readonly不显示测试维护", () => {
  const context = { ...tester, is_manager: true };
  const workflow = load("workflow-panel").PlanWorkflowPanel({
    base: "/q/",
    plan: { ...plan, status: "review" },
    context,
    onSaved: async () => {},
  });
  assert.ok(!labels(workflow).some((x) => ["确认测试结果", "退回复测"].includes(x)));
  const readonly = { ...tester, can_write: false };
  assert.ok(
    !labels(load("test-resources-panel").TestResourcesPanel({ base: "/q/", context: readonly })).includes(
      "登记测试资源"
    )
  );
});

test("缺陷与测试计划不再加载数据平台回归或Session关联入口", () => {
  for (const name of ["defect-detail", "plan-detail"]) {
    const source = readFileSync(new URL(`../core/components/quality/${name}.tsx`, import.meta.url), "utf8");
    assert.doesNotMatch(source, /DataRegressionPanel|DataEvidencePanel|data-regressions|data-evidence/);
  }
});

test("测试员可生成测试报告快照，不因报告维护获得项目发布或外发权限", () => {
  const tree = load("reports-panel").ReportsPanel({ base: "/q/", context: tester });
  assert.ok(labels(tree).includes("生成测试报告"));
  assert.ok(!nodes(tree).some((n) => n.type === stub("ReportDeliveryPanel")));
});
