import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const React = require("react");
const stubs = new Map();
const component = (name) => {
  if (!stubs.has(name)) stubs.set(name, () => null);
  return stubs.get(name);
};
function load(file, params, { loading = false, error = false, detail } = {}) {
  const exports = {};
  const code = ts.transpileModule(
    readFileSync(new URL(`../core/components/quality/${file}.tsx`, import.meta.url), "utf8"),
    {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }
  ).outputText;
  const context = { is_manager: true, can_write: true, members: [], capabilities: {}, business_roles_enabled: false };
  new Function("require", "exports", code)((id) => {
    if (id === "react")
      return {
        ...React,
        useState: (initial) => [initial === null && detail ? detail : initial, () => {}],
        useEffect() {},
      };
    if (id === "react/jsx-runtime") return require(id);
    if (id === "react-router")
      return { useParams: () => ({}), useLocation: () => ({ hash: "" }), useSearchParams: () => [params, () => {}] };
    if (id === "@/hooks/use-resolved-project-params")
      return { useResolvedProjectParams: () => ({ workspaceSlug: "qa", projectId: "p" }) };
    if (id === "swr")
      return {
        useSWRConfig: () => ({ mutate() {} }),
        default: (key) => ({
          data: key?.endsWith("context/")
            ? context
            : key?.includes("/?") && !loading
              ? { results: [], count: 0 }
              : undefined,
          isLoading: loading,
          error: error ? new Error("offline") : undefined,
          mutate() {},
        }),
      };
    if (id === "./pagination") return { normalizedPageParams: (value) => value, pageSize: () => 50 };
    if (id === "./types") return { can: () => true, canOpenQualityTab: () => true };
    if (id === "./layout-controls")
      return { LayoutControls: component("LayoutControls"), recordLayout: () => params.get("layout") || "list" };
    if (id === "./work-item-kind") return { useWorkItemKinds: () => ({}) };
    return new Proxy({}, { get: (_, name) => component(String(name)) });
  }, exports);
  return exports;
}
function nodes(tree) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
for (const [tab, layout, name, defectsOnly] of [
  ["cases", "list", "CaseList", false],
  ["cases", "table", "RecordPresentation", false],
  ["plans", "table", "RecordPresentation", false],
  ["executions", "table", "RecordPresentation", false],
  ["defects", "table", "RecordPresentation", true],
])
  test(`${tab}/${layout}筛空保留表头筛选，数量与空结果一致`, () => {
    const params = new URLSearchParams({ tab, layout, search: "missing", priority: "high" });
    const { QualityWorkbench } = load("workbench", params);
    const tree = QualityWorkbench({ defectsOnly });
    const list = nodes(tree).find((n) => n.type === component(name));
    assert.ok(list, "空结果不能移除含筛选按钮的表格");
    assert.equal(list.props.rows.length, 0);
    assert.equal(nodes(tree).find((n) => n.type === component("Paging")).props.count, 0);
  });
test("需求表格筛空保留状态等表头入口", () => {
  const { RequirementsWorkbench } = load(
    "requirements-workbench",
    new URLSearchParams("layout=table&status=cancelled")
  );
  const tree = RequirementsWorkbench();
  assert.ok(nodes(tree).some((n) => n.type === "table"));
  const labels = new Set(
    nodes(tree)
      .filter((n) => n.type === component("TableHeaderFilter"))
      .map((n) => n.props.label)
  );
  assert.ok(labels.has("状态"));
  assert.ok(labels.has("优先级"));
});
for (const kind of ["suites", "releases"])
  test(`${kind}空表格保留筛选入口`, () => {
    const { AssetsPanel } = load("assets-panel", new URLSearchParams());
    const tree = AssetsPanel({ base: "/qa/", kind, rows: [], context: {}, layout: "table", onSaved() {} });
    assert.ok(nodes(tree).some((n) => n.type === component("RecordPresentation") && n.props.rows.length === 0));
  });
test("正在加载或失败时不冒充成功的空表格", () => {
  for (const state of [{ loading: true }, { error: true }]) {
    const { QualityWorkbench } = load("workbench", new URLSearchParams("tab=cases&layout=table"), state);
    const tree = QualityWorkbench({});
    assert.ok(!nodes(tree).some((n) => n.type === component("RecordPresentation")));
  }
});
for (const name of ["CaseList", "RecordPresentation"])
  test(`${name}空结果显示在表格内且保留表头`, () => {
    const file = name === "CaseList" ? "record-lists" : "record-presentation";
    const exports = load(file, new URLSearchParams());
    const tree = exports[name]({
      rows: [],
      layout: "table",
      columns: ["优先级", "版本"],
      kind: "cases",
      onOpen() {},
      canWrite: true,
    });
    assert.ok(nodes(tree).some((n) => n.type === "thead"));
    const cell = nodes(tree).find((n) => n.type === "td" && n.props.role === "status");
    assert.ok(cell);
    assert.match(cell.props.children, /没有匹配记录/);
  });
for (const state of ["archived_at", "trashed_at"])
  test(`用例集${state}不提供会被后台拒绝的编辑和发布操作`, () => {
    const { AssetsPanel } = load("assets-panel", new URLSearchParams());
    const row = {
      id: "s1",
      name: "回归组合",
      description: "",
      published: false,
      edit_version: 2,
      items: [],
      archived_at: null,
      trashed_at: null,
      [state]: "2026-11-10T00:00:00Z",
    };
    const tree = AssetsPanel({
      base: "/qa/",
      kind: "suites",
      rows: [row],
      context: { is_manager: true },
      layout: "list",
      onSaved() {},
    });
    const text = new Set(
      nodes(tree)
        .map((n) => n.props?.children)
        .filter((value) => typeof value === "string")
    );
    assert.ok(!text.has("编辑草稿"));
    assert.ok(!text.has("发布用例集"));
    assert.equal(text.has("复制为新草稿"), state === "archived_at");
    assert.ok(text.has(state === "archived_at" ? "已归档" : "已删除"));
  });

for (const state of ["archived_at", "trashed_at"])
  test(`用例集详情${state}保留恢复菜单并禁用编辑发布`, () => {
    const detail = { id: "s1", name: "回归组合", description: "", published: false, items: [], [state]: "2026-11-10" };
    const { AssetsPanel } = load("assets-panel", new URLSearchParams(), { detail });
    const tree = AssetsPanel({ base: "/qa/", kind: "suites", rows: [], context: { is_manager: true }, onSaved() {} });
    const modal = nodes(tree).find((n) => n.type === component("Modal") && n.props.title === detail.name);
    assert.ok(modal);
    assert.ok(nodes(modal).some((n) => n.type === component("RecordLifecycleActions")));
    const labels = new Set(
      nodes(modal)
        .map((n) => n.props?.children)
        .filter((value) => typeof value === "string")
    );
    assert.ok(!labels.has("编辑草稿"));
    assert.ok(!labels.has("发布用例集"));
    assert.equal(labels.has("复制为新草稿"), state === "archived_at");
  });
