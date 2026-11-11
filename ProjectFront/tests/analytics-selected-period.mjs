import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
test("新增图请求跟随所选时间，完成子集文案不冒充当日完成事件", () => {
  const calls = [],
    exports = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/analytics/work-items/created-vs-resolved.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
    ).outputText
  )((id) => {
    if (id === "react/jsx-runtime") return require(id);
    if (id === "react") return { ...React, useMemo: (fn) => fn(), useState: (value) => [value, () => {}] };
    if (id === "mobx-react") return { observer: (fn) => fn };
    if (id === "next/navigation") return { useParams: () => ({ workspaceSlug: "w" }) };
    if (id === "swr")
      return {
        default: (key, fetcher) => {
          fetcher();
          return { data: { data: [{ key: "2026-11-10", created_issues: 4, completed_issues: 2 }] }, isLoading: false };
        },
      };
    if (id === "@plane/i18n") return { useTranslation: () => ({ t: String }) };
    if (id === "@plane/utils") return { renderFormattedDate: String };
    if (id === "@/hooks/store/use-analytics")
      return { useAnalytics: () => ({ selectedDuration: "last_7_days", selectedProjects: ["p"], isPeekView: false }) };
    if (id === "@/services/analytics.service")
      return {
        AnalyticsService: class {
          getAdvanceAnalyticsCharts(...args) {
            calls.push(args);
          }
        },
      };
    if (id === "@/components/quality/statistics-display") return { TrendChart: "chart" };
    if (id === "../analytics-section-wrapper") return { default: "section" };
    return new Proxy({}, { get: () => () => null });
  }, exports);
  const tree = exports.default().props.children[0];
  assert.equal(calls[0][2].date_filter, "last_7_days");
  assert.match(tree.props.subtitle, /7天/);
  const chart = tree.props.children;
  assert.equal(chart.props.series[1].label, "其中已完成");
});
