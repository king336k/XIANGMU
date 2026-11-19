import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
function load(file, overrides = {}) {
  const exports = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL("../core/components/" + file, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((id) => overrides[id] || require(id), exports);
  return exports;
}
const types = load("quality/types.ts");
test("new human follow-up states retain independent Chinese names and owner metrics", () => {
  assert.equal(types.statusNames.pending_tech, "待技术确认");
  assert.equal(types.statusNames.needs_tech, "待技术处理");
  const metrics = load("quality/owner-metrics.ts").defectOwnerMetrics;
  for (const key of ["pending_tech", "needs_tech"])
    assert.ok(metrics.some((metric) => metric.key === key && metric.label === types.statusNames[key]));
  const owner = load("quality/owner-statistics.ts");
  assert.equal(owner.ownerStatusNames.pending_tech, "待技术确认");
  assert.equal(owner.ownerStatusNames.needs_tech, "待技术处理");
});
test("agent badge uses short truthful states and a spinner only during active work", () => {
  const badge = load("quality/agent-processing-badge.tsx").AgentProcessingBadge;
  for (const [state, label] of Object.entries({
    queued: "排队中",
    inspect: "排查中",
    repair: "修复中",
    verify: "复测中",
    repaired: "已修复",
    verified: "复核通过",
    unresolved: "未解决",
    interrupted: "已中断",
  })) {
    const html = renderToStaticMarkup(
      React.createElement(badge, {
        value: { state, label: "overly long status", summary: "详细实际说明", run_id: "run" },
      })
    );
    assert.match(html, new RegExp(label));
    assert.match(html, /title="详细实际说明"/);
    assert.doesNotMatch(html, /overly long status/);
    assert.equal(html.includes("animate-spin"), ["queued", "inspect", "repair", "verify"].includes(state));
  }
  assert.equal(renderToStaticMarkup(React.createElement(badge, { value: null })), "");
});
test("short run labels keep stage distinct and recognize verified-without-repair in any mode", () => {
  const remote = load("remote-diagnostics/types.ts");
  assert.equal(
    remote.agentRunShortLabel({ status: "queued", queue: { reason: "terminal_open", position: 2 } }),
    "排队中"
  );
  assert.equal(remote.agentRunShortLabel({ status: "running", queue: { stage: "verify" } }), "复测中");
  assert.equal(
    remote.agentRunShortLabel({
      status: "completed",
      mode: "repair",
      result: { repaired: false, verification_passed: true, outcome: "verified_without_repair" },
    }),
    "复核通过"
  );
  assert.equal(
    remote.agentRunShortLabel({ status: "completed", result: { repaired: true, verification_passed: false } }),
    "未解决"
  );
  assert.equal(remote.agentRunShortLabel({ status: "failed" }), "已中断");
});

const nodes = (tree) =>
  !tree || typeof tree !== "object"
    ? []
    : Array.isArray(tree)
      ? tree.flatMap(nodes)
      : [tree, ...nodes(tree.props?.children)];
test("detail shows independent short agent status and safe role-gated workflow actions", () => {
  let state = [],
    edits = [];
  const badge = load("quality/agent-processing-badge.tsx");
  const { DefectDetail } = load("quality/defect-detail.tsx", {
    react: { useState: (initial) => [initial, (value) => state.push(value)] },
    "./types": { ...types, can: (context) => context.can_write },
    "./agent-processing-badge": badge,
    "@plane/utils": {},
    "@/components/common/project-route-link": { ProjectRouteLink: () => null },
    ...Object.fromEntries(
      [
        "defect-report-edit",
        "api",
        "defect-quick-edit",
        "defect-reassign",
        "shared",
        "defect-attachments",
        "collaboration-panel",
        "defect-disposition",
        "diagnostics-panel",
        "deployment-snapshots",
        "defect-team",
        "solution-panel",
        "defect-verification-scope",
        "verification-assignee",
        "defect-comments",
        "agent-feedback-results",
        "record-progress",
      ].map((name) => ["./" + name, new Proxy({}, { get: (_, key) => (key === "resolutionNames" ? {} : () => null) })])
    ),
  });
  const render = (status, manager = false, writable = true) =>
    DefectDetail({
      base: "/q/",
      projectUrl: "/p",
      value: {
        id: "d",
        title: "问题",
        status,
        assignee_id: "tech",
        resolution_kind: "fixed",
        agent_processing: { state: "repaired", run_id: "run" },
      },
      context: { can_write: writable, user_id: "tech", is_manager: manager, members: [] },
      onEdit: (mode) => edits.push(mode),
      onClose() {},
      onChanged: async () => {},
    });
  let tree = render("pending_tech");
  assert.ok(nodes(tree).some((node) => node.type === badge.AgentProcessingBadge));
  nodes(tree)
    .find((node) => node.type === "button" && node.props.children === "查看处理")
    .props.onClick();
  assert.ok(state.includes("diagnosis"));
  nodes(tree)
    .find((node) => node.type === "button" && node.props.children === "继续处理")
    .props.onClick();
  assert.deepEqual(edits, ["workflow"]);
  assert.ok(!nodes(tree).some((node) => node.type === "button" && node.props.children === "确认关闭"));
  tree = render("resolved", true);
  nodes(tree)
    .find((node) => node.type === "button" && node.props.children === "确认关闭")
    .props.onClick();
  assert.ok(state.includes("regression"));
  assert.deepEqual(edits, ["workflow"]);
  tree = render("pending_tech", false, false);
  assert.ok(
    !nodes(tree).some((node) => node.type === "button" && ["继续处理", "确认关闭"].includes(node.props.children))
  );
});

test("all list layouts show agent status beside the unchanged defect workflow status", () => {
  const badge = load("quality/agent-processing-badge.tsx");
  const { RecordPresentation } = load("quality/record-presentation.tsx", {
    "./agent-processing-badge": badge,
    "./record-badge": { Badge: ({ label }) => label },
    "./table-header-filter": { TableHeaderFilter: ({ label }) => label },
  });
  for (const layout of ["list", "table", "board"]) {
    const html = renderToStaticMarkup(
      React.createElement(RecordPresentation, {
        layout,
        kind: "defects",
        columns: [],
        onOpen() {},
        rows: [
          {
            id: "d",
            title: "问题",
            status: "pending_tech",
            statusName: "待技术确认",
            values: [],
            agentProcessing: { state: "verified", run_id: "run" },
          },
        ],
      })
    );
    assert.match(html, /待技术确认/);
    assert.match(html, /复核通过/);
  }
});
test("notification values translate both new defect states and preserve unknown native issue states", () => {
  const notifications = load("workspace-notifications/notification-card/content.ts");
  assert.equal(notifications.renderAdditionalValue("status", "pending_tech"), "待技术确认");
  assert.equal(notifications.renderAdditionalValue("state", "needs_tech"), "待技术处理");
  assert.equal(notifications.renderAdditionalValue("state", "Custom state"), "Custom state");
});

test("new follow-up states use the existing repair workflow and never directly allow closed", () => {
  const form = readFileSync(new URL("../core/components/quality/defect-form.tsx", import.meta.url), "utf8");
  for (const state of ["pending_tech", "needs_tech"]) {
    const choices = new RegExp(state + ": \\[([^\\]]+)\\]").exec(form)[1];
    assert.match(choices, /"in_progress"/);
    assert.match(choices, /"resolved"/);
    assert.doesNotMatch(choices, /"closed"/);
  }
  assert.match(form, /current && !editing/);
  assert.match(form, /onSuccess:.*snapshot/);
});
