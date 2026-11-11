import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const stubs = new Map();
function stub(name) {
  if (!stubs.has(name)) stubs.set(name, () => null);
  return stubs.get(name);
}
function descendants(tree) {
  if (!tree || typeof tree !== "object") return [];
  return Array.isArray(tree) ? tree.flatMap(descendants) : [tree, ...descendants(tree.props?.children)];
}
function visibleHostChildren(tree) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(visibleHostChildren);
  return tree.type === React.Fragment ? visibleHostChildren(tree.props.children) : [tree];
}
function render({ tab = "defects", manager = true, results = true } = {}) {
  const exp = {},
    updates = [],
    params = new URLSearchParams(`tab=${tab}&page=4&severity=major`);
  const context = {
    is_manager: manager,
    can_write: manager,
    capabilities: {},
    business_roles_enabled: false,
    members: [],
  };
  const row =
    tab === "defects"
      ? { id: "d", title: "异常", severity: "major", status: "open" }
      : tab === "cases"
        ? { id: "c", title: "用例", steps: [], module: "", version: 1 }
        : { id: "p", name: "计划", summary: { total: 1, executed: 0, failed: 0 }, status: "ready", build: "v1" };
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL("../core/components/quality/workbench.tsx", import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((id) => {
    if (id === "react/jsx-runtime") return require(id);
    if (id === "react") return { ...React, useState: (value) => [value, () => {}], useEffect() {} };
    if (id === "react-router")
      return {
        useSearchParams: () => [params, (value) => updates.push(value)],
        useLocation: () => ({ hash: "" }),
        useParams: () => ({}),
      };
    if (id === "@/hooks/use-resolved-project-params")
      return { useResolvedProjectParams: () => ({ workspaceSlug: "w", projectId: "p" }) };
    if (id === "swr")
      return {
        default: (key) => ({
          data: key?.endsWith("context/")
            ? context
            : key?.includes("/?")
              ? { results: results ? [row] : [], count: results ? 1 : 0 }
              : undefined,
          isLoading: false,
          mutate: async () => {},
        }),
        useSWRConfig: () => ({ mutate: async () => {} }),
      };
    if (id === "./pagination") return { normalizedPageParams: (value) => value, pageSize: () => 20 };
    if (id === "./layout-controls") return { recordLayout: () => "table" };
    if (id === "./types")
      return {
        can: () => manager,
        canOpenQualityTab: () => true,
        defectDisplayTitle: (value) => value,
        severityNames: {},
        priorityNames: {},
        statusNames: {},
        planStatusNames: {},
        resultNames: {},
      };
    return new Proxy({}, { get: (_, key) => stub(String(key)) });
  }, exp);
  return { tree: exp.QualityWorkbench({ defectsOnly: tab === "defects" }), updates };
}
function toolbar(tree) {
  return descendants(tree).find((node) => {
    const children = visibleHostChildren(node.props?.children);
    return (
      children.some((child) => child.type === "nav" && child.props["aria-label"] === "缺陷快捷视图") &&
      children.some((child) => descendants(child).some((item) => item.type === stub("BulkActionsBar")))
    );
  });
}

test("缺陷快捷视图与批量操作共享一个可自然换行的DOM工具行，不再分成上下两块", () => {
  const { tree } = render();
  const row = toolbar(tree);
  assert.ok(row, "快捷视图和批量维护必须在同一紧凑工具行");
  assert.match(row.props.className, /\bflex\b/);
  assert.match(row.props.className, /flex-wrap/);
  assert.doesNotMatch(row.props.className, /(?:min-)?h-\d|grid-rows/);
  assert.equal(descendants(tree).filter((node) => node.type === stub("BulkActionsBar")).length, 1);
});
test("工具行合并保持快捷筛选URL语义，空列表和普通成员仍不出现批量维护", () => {
  const { tree, updates } = render();
  const quick = descendants(tree).find((node) => node.type === "nav" && node.props["aria-label"] === "缺陷快捷视图");
  descendants(quick)
    .find((node) => node.type === "button" && node.props.children === "指派给我")
    .props.onClick();
  assert.equal(updates[0].get("view"), "assigned_to_me");
  assert.equal(updates[0].has("page"), false);
  assert.equal(updates[0].get("severity"), "major");
  for (const options of [{ manager: false }, { results: false }])
    assert.equal(descendants(render(options).tree).filter((node) => node.type === stub("BulkActionsBar")).length, 0);
});
for (const tab of ["cases", "plans"])
  test(`${tab}仍保留单个已授权的批量入口`, () => {
    const tree = render({ tab }).tree;
    assert.equal(descendants(tree).filter((node) => node.type === stub("BulkActionsBar")).length, 1);
    assert.equal(
      descendants(tree).filter((node) => node.type === "nav" && node.props["aria-label"] === "缺陷快捷视图").length,
      0
    );
  });
