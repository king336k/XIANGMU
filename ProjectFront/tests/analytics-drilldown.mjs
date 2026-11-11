import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
function load(file, mocks = {}) {
  const exports = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/analytics/" + file + ".tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }
    ).outputText
  )(
    (id) =>
      mocks[id] ??
      (id === "react" || id === "react/jsx-runtime" ? require(id) : new Proxy({}, { get: () => () => null })),
    exports
  );
  return exports;
}
function nodes(t) {
  if (!t || typeof t !== "object") return [];
  return Array.isArray(t) ? t.flatMap(nodes) : [t, ...nodes(t.props?.children)];
}
test("统计卡片可键盘点击打开明细，加载时不误点", () => {
  const Card = load("insight-card").default;
  let opened = 0;
  const tree = Card({ data: { count: 12 }, label: "工作项总数", onClick: () => opened++ });
  assert.equal(tree.type, "button");
  tree.props.onClick();
  assert.equal(opened, 1);
  assert.equal(tree.props["aria-label"], "查看工作项总数明细，共12条");
  assert.equal(Card({ data: { count: 12 }, label: "工作项总数", isLoading: true, onClick() {} }).props.disabled, true);
});
test("顶部卡片点击保留项目周期模块范围，弹窗按实际指标查询", () => {
  const Card = () => null,
    Modal = () => null;
  const states = [];
  let i = 0;
  const hooks = {
    ...React,
    useState: (v) => {
      let k = i++;
      if (!(k in states)) states[k] = v;
      return [states[k], (v) => (states[k] = v)];
    },
  };
  const exports = load("total-insights", {
    react: hooks,
    "mobx-react": { observer: (f) => f },
    "next/navigation": { useParams: () => ({ workspaceSlug: "w" }) },
    swr: { default: () => ({ data: { total_work_items: { count: 12 } }, isLoading: false }) },
    "@plane/constants": { ANALYTICS_INSIGHTS_FIELDS: { "work-items": [{ key: "total_work_items", i18nKey: "总数" }] } },
    "@plane/i18n": { useTranslation: () => ({ t: String }) },
    "@plane/utils": { cn: () => "" },
    "@/hooks/store/use-analytics": {
      useAnalytics: () => ({
        selectedDuration: "last_7_days",
        selectedProjects: ["p"],
        selectedCycle: "c",
        selectedModule: "m",
        isPeekView: true,
      }),
    },
    "@/services/analytics.service": { AnalyticsService: class {} },
    "./insight-card": { default: Card },
    "./analytics-details": { AnalyticsDetails: Modal },
  });
  let tree = exports.default({ analyticsType: "work-items" });
  const card = nodes(tree).find((n) => n.type === Card);
  assert.equal(typeof card.props.onClick, "function");
  card.props.onClick();
  i = 0;
  tree = exports.default({ analyticsType: "work-items" });
  const modal = nodes(tree).find((n) => n.type === Modal);
  assert.ok(modal);
  assert.equal(modal.props.metric, "total_work_items");
  assert.deepEqual(modal.props.filters, { project_ids: "p", cycle_id: "c", module_id: "m" });
  assert.equal(modal.props.isPeekView, true);
});
test("明细翻页、条数和链接始终保留原指标项目范围", () => {
  const states = [];
  let i = 0,
    query;
  const Paging = () => null,
    Link = () => null;
  const hooks = {
    ...React,
    useState: (v) => {
      const k = i++;
      if (!(k in states)) states[k] = v;
      return [states[k], (n) => (states[k] = typeof n === "function" ? n(states[k]) : n)];
    },
    useEffect() {},
  };
  const read = (path) => readFileSync(new URL("../core/components/" + path, import.meta.url), "utf8");
  const exports = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(read("quality/use-collection-pagination.tsx"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS },
    }).outputText
  )((id) => (id === "react" ? hooks : require(id)), exports);
  const { AnalyticsDetails } = load("analytics-details", {
    "next/navigation": { useParams: () => ({ workspaceSlug: "w" }) },
    swr: {
      default: (q) => {
        query = q;
        return {
          data: {
            count: 61,
            results: [{ id: "u", title: "成员", kind: "成员", subtitle: "研发", url: "/w/profile/u/" }],
          },
          isLoading: false,
        };
      },
    },
    "@/components/quality/use-collection-pagination": exports,
    "@/components/quality/shared": { Modal: () => null, Paging },
    "@/components/common/project-route-link": { ProjectRouteLink: Link },
  });
  const props = { title: "用户总数", metric: "total_users", filters: { project_ids: "p" }, onClose() {} };
  let tree = AnalyticsDetails(props);
  assert.ok(query.includes("detail=total_users") && query.includes("project_ids=p") && query.includes("per_page=20"));
  const link = nodes(tree).find((n) => n.type === Link);
  assert.equal(link.props.to, "/w/profile/u/");
  nodes(tree)
    .find((n) => n.type === Paging)
    .props.onChange(2);
  i = 0;
  tree = AnalyticsDetails(props);
  assert.ok(query.includes("page=2"));
  nodes(tree)
    .find((n) => n.type === Paging)
    .props.onPageSizeChange(50);
  i = 0;
  AnalyticsDetails(props);
  assert.ok(query.includes("page=1") && query.includes("per_page=50"));
});
