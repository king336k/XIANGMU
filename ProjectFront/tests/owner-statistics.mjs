import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
function load(file, mocks = {}) {
  const exports = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL("../core/components/quality/" + file, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
    }).outputText
  )(
    (id) =>
      mocks[id] ??
      (id === "react" || id === "react/jsx-runtime" ? require(id) : new Proxy({}, { get: () => () => null })),
    exports
  );
  return exports;
}
function nodes(t) {
  return !t || typeof t !== "object" ? [] : Array.isArray(t) ? t.flatMap(nodes) : [t, ...nodes(t.props?.children)];
}
test("owner detail keeps original filters and intersects status through owner_status without replacing page filters", () => {
  const { ownerStatisticsQuery } = load("owner-statistics.ts");
  const params = new URLSearchParams(
    "status=open&exclude_status=closed&project_ids=p1%2Cp2&created_after=2026-11-01&page=8&per_page=50&owner_id=old&owner_metric=closed"
  );
  const query = ownerStatisticsQuery(params, "defects", "total", 2, { owner_id: "unassigned", status: "in_progress" });
  assert.equal(query.get("status"), "open");
  assert.equal(query.get("exclude_status"), "closed");
  assert.equal(query.get("owner_status"), "in_progress");
  assert.equal(query.get("owner_id"), "unassigned");
  assert.equal(query.get("page"), "2");
  assert.equal(query.get("per_page"), "20");
  assert.equal(query.get("metric"), "total");
  assert.equal(query.get("project_ids"), "p1,p2");
  assert.equal(query.has("owner_metric"), false);
  const summary = ownerStatisticsQuery(params, "defects", "total", 3);
  assert.equal(summary.has("owner_id"), false);
  assert.equal(summary.get("per_page"), "10");
  assert.equal(params.get("page"), "8");
});
const Paging = () => null,
  Modal = () => null,
  Stats = () => null;
test("owner row status and count open paginated detail with URL state while preserving the page filters", () => {
  let route = new URLSearchParams("panel=statistics&status=open&owner_metric=total"),
    query;
  const hooks = { ...React, useEffect() {} };
  const { OwnerSummary } = load("owner-summary.tsx", {
    react: hooks,
    "react-router": {
      useLocation: () => ({ pathname: "/w/quality", search: "?" + route }),
      useSearchParams: () => [
        route,
        (next) => {
          route = next;
        },
      ],
    },
    swr: {
      default: (url) => {
        if (!url) return {};
        query = url;
        return {
          data: url.includes("owner_id=")
            ? {
                count: 30,
                results: [
                  {
                    id: "d",
                    title: "异常",
                    url: "/w/projects/p/defects/d/",
                    status: "open",
                    kind: "缺陷",
                    project_name: "项目",
                  },
                ],
              }
            : {
                count: 21,
                total: 37,
                results: [
                  {
                    owner_id: "u",
                    name: "技术员甲",
                    active: true,
                    count: 5,
                    statuses: [
                      { status: "open", count: 3 },
                      { status: "closed", count: 2 },
                    ],
                  },
                ],
                ownership_basis: "当前负责人",
              },
        };
      },
    },
    "./owner-statistics": load("owner-statistics.ts"),
    "./shared": { Modal, Paging, fieldClass: "" },
    "./record-badge": { Badge: () => null },
  });
  const props = {
    endpoint: "/owner-statistics/",
    source: "defects",
    params: new URLSearchParams("status=open"),
    metrics: [{ key: "total", label: "缺陷" }],
  };
  let tree = OwnerSummary(props);
  const button = nodes(tree).find((n) => n.type === "button" && n.props["aria-label"] === "技术员甲 · 待处理 3条");
  assert.ok(button);
  button.props.onClick();
  assert.equal(route.get("owner_id"), "u");
  assert.equal(route.get("owner_status"), "open");
  assert.equal(route.get("status"), "open");
  tree = OwnerSummary(props);
  assert.ok(query.includes("owner_id=u") && query.includes("owner_status=open") && query.includes("per_page=20"));
  const modal = nodes(tree).find((n) => n.type === Modal);
  assert.ok(modal);
  modal.props.onClose();
  assert.equal(route.has("owner_id"), false);
  assert.equal(route.get("status"), "open");
});

test("statistics return link accepts only same workspace internal paths and keeps owner modal filters", () => {
  const { statisticsReturnPath } = load("statistics-return-link.tsx");
  const target = "/w/projects/p/quality?tab=overview&owner_id=u&owner_status=failed&owner_detail_page=2";
  assert.equal(statisticsReturnPath(target, "/w/projects/p/quality"), target);
  for (const value of ["https://evil.test", "//evil.test", "/other/analytics", "/w/\\evil"])
    assert.equal(statisticsReturnPath(value, "/w/projects/p/defects"), null);
});
test("readonly and unassigned owner distributions open readable details without granting edit permission", () => {
  const source = readFileSync(
    new URL("../core/components/core/sidebar/progress-stats/assignee.tsx", import.meta.url),
    "utf8"
  );
  assert.match(source, /onOpenAssignee/);
  assert.match(source, /onOpenAssignee\?\.\(assignee.id \|\| "unassigned"/);
  assert.match(source, /canView/);
});

test("readonly owner and unassigned buttons read details without writing filters; snapshots stay static", () => {
  const opened = [],
    edited = [];
  const { AssigneeStatComponent } = load("../core/sidebar/progress-stats/assignee.tsx", {
    "mobx-react": { observer: (value) => value },
    "@plane/i18n": { useTranslation: () => ({ t: () => "未指派" }) },
    "@plane/utils": { getFileURL: (value) => value },
    "@/components/core/sidebar/single-progress-stats": { SingleProgressStats: Stats },
  });
  const props = {
    isEditable: false,
    selectedAssigneeIds: [],
    distribution: [
      { id: "u", title: "技术员甲", completed: 1, total: 4 },
      { id: undefined, completed: 0, total: 2 },
    ],
    onOpenAssignee: (...value) => opened.push(value),
    handleAssigneeFiltersUpdate: (value) => edited.push(value),
  };
  let tree = AssigneeStatComponent(props);
  const rows = nodes(tree).filter((n) => n.type === Stats);
  rows[0].props.onClick();
  rows[1].props.onClick();
  assert.deepEqual(opened, [
    ["u", "技术员甲"],
    ["unassigned", "未指派"],
  ]);
  assert.deepEqual(edited, []);
  tree = AssigneeStatComponent({ ...props, canView: false });
  assert.ok(
    nodes(tree)
      .filter((n) => n.type === Stats)
      .every((n) => !n.props.onClick)
  );
});
test("owner indicators cover same metrics as each statistic source and distinguish actual execution from technical assignment", () => {
  const { qualityOwnerMetrics, analyticsOwnerMetrics, periodOwnerMetrics } = load("owner-metrics.ts");
  assert.ok(qualityOwnerMetrics.some((item) => item.key === "execution_count"));
  assert.ok(qualityOwnerMetrics.some((item) => item.key === "manual_execution_count"));
  assert.ok(qualityOwnerMetrics.some((item) => item.key === "summary_pending"));
  for (const key of [
    "total_projects",
    "total_pages",
    "total_cycles",
    "total_modules",
    "total_views",
    "total_users",
    "total_work_items",
  ])
    assert.ok(analyticsOwnerMetrics.some((item) => item.key === key));
  assert.equal(new Set(periodOwnerMetrics.map((item) => item.key)).size, 11);
});

test("owner modal scope separates project overview from the open plan and preserves full filter intersections", () => {
  const { ownerStatisticsScope } = load("owner-statistics.ts");
  assert.notEqual(
    ownerStatisticsScope("/q/", "quality", new URLSearchParams()),
    ownerStatisticsScope("/q/", "quality", new URLSearchParams("plan_id=plan"))
  );
  assert.notEqual(
    ownerStatisticsScope("/q/", "quality", new URLSearchParams("plan_id=plan")),
    ownerStatisticsScope("/q/", "quality", new URLSearchParams("verification_id=round"))
  );
  assert.equal(
    ownerStatisticsScope("/q/", "defects", new URLSearchParams("status=open&page=1")),
    ownerStatisticsScope("/q/", "defects", new URLSearchParams("page=8&status=open&owner_id=u&owner_scope=old"))
  );
});
