import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const React = require("react"),
  ts = require("typescript");
const stubs = new Map();
function stub(name) {
  if (!stubs.has(name)) {
    const value = () => name && null;
    value.MenuItem = () => null;
    stubs.set(name, value);
  }
  return stubs.get(name);
}
const walk = (t) =>
  !t || typeof t !== "object" ? [] : Array.isArray(t) ? t.flatMap(walk) : [t, ...walk(t.props?.children)];
function load(params, context) {
  const exp = {},
    keys = [],
    changes = [];
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/quality/versions-workbench.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }
    ).outputText
  )((id) => {
    if (id === "react") return { ...React, useState: (v) => [typeof v === "function" ? v() : v, () => {}] };
    if (id === "react/jsx-runtime") return require(id);
    if (id === "react-router")
      return {
        useParams: () => ({ projectId: "NAV" }),
        useSearchParams: () => [new URLSearchParams(params), (next) => changes.push(next)],
      };
    if (id === "@/hooks/use-resolved-project-params")
      return { useResolvedProjectParams: () => ({ workspaceSlug: "w", projectId: "uuid" }) };
    if (id === "swr")
      return {
        default: (key) => {
          keys.push(key);
          return {
            data: key?.includes("context/")
              ? context
              : key?.includes("versions/selected-v/")
                ? undefined
                : { results: [], count: 0 },
            mutate: async () => {},
          };
        },
      };
    if (id === "./pagination") return { pageSize: () => 20 };
    return new Proxy({}, { get: (_, key) => stub(key) });
  }, exp);
  return { tree: exp.VersionsWorkbench(), keys, changes };
}
test("版本发布验收使用独立发布列表，保留所选版本和页码，不误查UUID为版本详情", () => {
  const result = load("tab=acceptance&version=selected-v&page=2", { identifier: "NAV", project_name: "导航项目" });
  const panel = walk(result.tree).find((n) => n.type === stub("VersionAcceptancePanel"));
  assert.ok(panel, "acceptance belongs to versions");
  assert.equal(panel.props.base, "/api/workspaces/w/projects/uuid/quality/");
  assert.ok(!result.keys.some((k) => k?.includes("versions/selected-v/")), result.keys);
});
test("版本页提供发布验收入口并保留其他查询，原版本列表仍默认显示", () => {
  const result = load("version=selected-v&display=timeline", { identifier: "NAV", project_name: "导航项目" });
  const link = walk(result.tree).find((n) => n.props?.children === "发布验收");
  assert.ok(link);
  link.props.onClick();
  assert.equal(result.changes[0].get("tab"), "acceptance");
  assert.equal(result.changes[0].get("version"), "selected-v");
  assert.equal(result.changes[0].get("display"), "timeline");
});

test("发布验收筛选不把版本选择和展示方式算成筛选，清筛选仍保留返回位置", () => {
  const exp = {},
    changes = [];
  const params = new URLSearchParams("tab=acceptance&version=selected-v&display=timeline&build=v1&page=2");
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/quality/version-acceptance-panel.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }
    ).outputText
  )((id) => {
    if (id === "react/jsx-runtime") return require(id);
    if (id === "react-router") return { useSearchParams: () => [params, (next) => changes.push(next)] };
    if (id === "swr") return { default: () => ({ data: { results: [], count: 0 }, mutate: async () => {} }) };
    if (id === "./pagination") return { normalizedPageParams: (p) => new URLSearchParams(p), pageSize: () => 50 };
    return new Proxy({}, { get: (_, key) => stub(key) });
  }, exp);
  const tree = exp.VersionAcceptancePanel({ base: "/q/", context: {} });
  const filters = walk(tree).find((n) => n.type === stub("ListFilters"));
  assert.equal(filters.props.params.has("version"), false);
  assert.equal(filters.props.params.has("display"), false);
  filters.props.onApply(new URLSearchParams("tab=acceptance&page=1"));
  assert.equal(changes[0].get("version"), "selected-v");
  assert.equal(changes[0].get("display"), "timeline");
  assert.equal(changes[0].get("tab"), "acceptance");
  assert.equal(changes[0].has("build"), false);
});
