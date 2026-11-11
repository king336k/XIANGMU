import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  React = require("react"),
  ts = require("typescript");
function render(details) {
  const api = {},
    Disclosure = Object.assign(() => null, { Button: () => null, Panel: () => null });
  const mocks = {
    react: { ...React, useMemo: (fn) => fn(), useState: (value) => [value, () => {}] },
    "mobx-react": { observer: (fn) => fn },
    "next/navigation": { useSearchParams: () => new URLSearchParams() },
    "@headlessui/react": { Disclosure, Transition: () => null },
    "@plane/i18n": { useTranslation: () => ({ t: (key) => key }) },
    "@plane/constants": { EEstimateSystem: { POINTS: "points" } },
    "@plane/types": { EIssuesStoreType: { MODULE: "module" } },
    "@plane/utils": { getDate: (value) => (value && !Number.isNaN(Date.parse(value)) ? new Date(value) : undefined) },
    "@/hooks/store/estimates": { useProjectEstimates: () => ({ areEstimateEnabledByProjectId: () => false }) },
    "@/hooks/store/use-module": {
      useModule: () => ({ getPlotTypeByModuleId: () => "burndown", getModuleById: () => details }),
    },
    "@/hooks/store/work-item-filters/use-work-item-filters": {
      useWorkItemFilters: () => ({ getFilter: () => undefined, updateFilterValueFromSidebar() {} }),
    },
  };
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/modules/analytics-sidebar/issue-progress.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
    ).outputText
  )((id) => mocks[id] || (id === "react/jsx-runtime" ? require(id) : new Proxy({}, { get: () => () => null })), api);
  const tree = api.ModuleAnalyticsProgress({ workspaceSlug: "w", projectId: "p", moduleId: "m" });
  function text(node) {
    if (node == null || typeof node === "boolean") return "";
    if (typeof node !== "object") return String(node);
    if (Array.isArray(node)) return node.map(text).join(" ");
    return text(node.props?.children);
  }
  return text(tree.props.children.props.children({ open: false }));
}
test("模块没有日期时显示未设置，不误报日期无效", () => {
  assert.match(render({}), /未设置日期/);
  assert.doesNotMatch(render({}), /invalid_date/);
});
test("未来日期和无效日期分别显示，统计分母零时不显示Infinity", () => {
  assert.match(render({ start_date: "2099-01-01", target_date: "2099-01-02" }), /尚未开始/);
  assert.match(render({ start_date: "bad", target_date: "bad" }), /日期无效/);
  assert.doesNotMatch(
    render({ start_date: "2020-01-01", target_date: "2020-02-01", completed_issues: 1, total_issues: 0 }),
    /Infinity/
  );
});
