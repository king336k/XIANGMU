import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
function load(name, mocks = {}) {
  const exp = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(`../core/components/quality/${name}`, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )(
    (id) =>
      mocks[id] ||
      (id === "react" || id === "react/jsx-runtime" || id === "uuid"
        ? require(id)
        : new Proxy({}, { get: () => () => null })),
    exp
  );
  return exp;
}
const types = load("verification-types.ts");
const Badge = ({ value, label }) => React.createElement("span", { "data-tone": value }, label || value);
const round = {
  id: "r",
  round_no: 1,
  mode: "manual",
  status: "returned_repair",
  fixed_build: "11",
  environment: "本地",
  steps: [{ action: "打开", expected: "成功" }],
  items: [],
  summary: { total: 1, passed: 0, failed: 1, pending: 0 },
  manual_results: [
    {
      id: "latest",
      result: "failed",
      actual_result: "最新实测失败",
      evidence: "日志B",
      created_at: "2026-11-12T10:00:00Z",
      step_results: [],
    },
    {
      id: "old",
      result: "passed",
      actual_result: "旧实测成功",
      evidence: "日志A",
      created_at: "2026-11-12T09:00:00Z",
      step_results: [],
    },
  ],
  events: [],
};
function renderRound(value = round) {
  const { VerificationRoundView } = load("verification-round-view.tsx", {
    "./verification-types": types,
    "./shared": { Badge },
    "@plane/utils": { renderNumericDateTime: String },
  });
  return renderToStaticMarkup(React.createElement(VerificationRoundView, { round: value }));
}
test("验证状态使用语义颜色，退回修复红色且待验收与已验收可区分", () => {
  assert.equal(types.verificationStatusTone.returned_repair, "failed");
  assert.equal(types.verificationStatusTone.review, "review");
  assert.equal(types.verificationStatusTone.accepted, "passed");
  assert.match(renderRound(), /data-tone="failed"[^>]*>退回修复/);
});
test("最新人工结果直接可见，旧执行保存在默认折叠的历史记录中", () => {
  const html = renderRound();
  assert.match(html, /验证结果/);
  assert.match(html, /最新实测失败/);
  assert.match(html, /<details[^>]*>[\s\S]*此前结果（1）[\s\S]*旧实测成功/);
  assert.doesNotMatch(html, /<details[^>]*open[^>]*>[\s\S]*此前结果（1）/);
});
test("按缺陷列表区分版本、退回状态和通过失败数，手机可换行", () => {
  const { DefectVerificationResults } = load("defect-verification-results.tsx", {
    react: { ...React, useState: (v) => [v, () => {}] },
    swr: {
      default: () => ({
        data: { count: 1, results: [{ defect_id: "d", code: "BASEKNOW-D-3", title: "数据异常", current: round }] },
      }),
    },
    "./verification-types": types,
    "./shared": {
      Badge,
      Field: ({ label, children }) => React.createElement("label", null, label, children),
      Paging: () => null,
      fieldClass: "field",
    },
  });
  const html = renderToStaticMarkup(React.createElement(DefectVerificationResults, { base: "/q/", projectUrl: "/p/" }));
  assert.match(html, /版本 11/);
  assert.match(html, /data-tone="failed"[^>]*>退回修复/);
  assert.match(html, /data-tone="neutral"[^>]*>通过 0\/1/);
  assert.match(html, /data-tone="failed"[^>]*>失败 1/);
  assert.match(html, /flex-wrap/);
});

test("步骤表并排展示预期与真实结果，手机使用逐行布局", () => {
  const { VerificationStepsTable } = load("verification-steps-table.tsx", { "./shared": { Badge } });
  const html = renderToStaticMarkup(
    React.createElement(VerificationStepsTable, {
      steps: [{ action: "打开界面", expected: "显示正常" }],
      results: [{ result: "failed", actual: "显示错误" }],
    })
  );
  for (const label of ["验证操作", "预期结果", "实际结果", "打开界面", "显示正常", "显示错误"])
    assert.ok(html.includes(label), label);
  assert.match(html, /data-tone="failed"/);
  assert.match(html, /sm:table-cell/);
});

const View = () => null;
const Form = () => null;
const Table = () => null;
const descendants = (tree) =>
  !tree || typeof tree !== "object"
    ? []
    : Array.isArray(tree)
      ? tree.flatMap(descendants)
      : [tree, ...descendants(tree.props?.children)];
test("结果列选择绑定当前步骤并打开原轮次实测表单，历史轮次没有编辑回调", () => {
  const changes = [];
  const tableApi = load("verification-steps-table.tsx", {
    react: { ...React, useMemo: (fn) => fn() },
    "./shared": { Badge },
    "./types": { resultNames: { passed: "通过", failed: "失败", pending: "未执行" } },
  });
  const table = tableApi.VerificationStepsTable({
    steps: [
      { action: "第一步", expected: "成功" },
      { action: "第二步", expected: "成功" },
    ],
    onResultChange: (index, result) => changes.push([index, result]),
  });
  descendants(table)
    .find((node) => node.type === "select" && node.props["aria-label"] === "步骤 2 结果")
    .props.onChange({ target: { value: "failed" } });
  assert.deepEqual(changes, [[1, "failed"]]);

  const current = {
    ...round,
    id: "current",
    version: 2,
    status: "testing",
    can_record: true,
    steps: [
      { action: "第一步", expected: "成功" },
      { action: "第二步", expected: "成功" },
    ],
  };
  const data = {
    defect_id: "d",
    defect_status: "resolved",
    defect_version: 7,
    current,
    history: [{ ...current, id: "historical", can_record: false }],
  };
  const state = [];
  let cursor = 0;
  const { DefectVerificationScope } = load("defect-verification-scope.tsx", {
    react: {
      ...React,
      useEffect() {},
      useState: (initial) => {
        const index = cursor++;
        if (!(index in state)) state[index] = typeof initial === "function" ? initial() : initial;
        return [
          state[index],
          (value) => {
            state[index] = value;
          },
        ];
      },
    },
    swr: { default: () => ({ data, mutate: async () => {} }) },
    "./verification-types": types,
    "./types": { can: () => true },
    "./verification-round-view": { VerificationRoundView: View },
    "./verification-manual-result": { VerificationManualResult: Form },
    "./shared": { Badge },
  });
  const render = () => {
    cursor = 0;
    return DefectVerificationScope({
      base: "/q/",
      value: { id: "d", edit_version: 7, status: "resolved", fixed_build: "11" },
      context: { members: [] },
      onChanged: async () => {},
    });
  };
  const views = descendants(render()).filter((node) => node.type === View);
  assert.equal(typeof views[0].props.onManualResultChange, "function");
  assert.equal(views[1].props.onManualResultChange, undefined);
  views[0].props.onManualResultChange(...changes[0]);
  data.current = { ...current, id: "next", version: 4, round_no: 2 };
  const form = descendants(render()).find((node) => node.type === Form);
  assert.equal(form.props.round.id, "current");
  assert.equal(form.props.round.version, 2);
  assert.equal(form.props.initialStepIndex, 1);
  assert.equal(form.props.initialResult, "failed");

  const { VerificationRoundView } = load("verification-round-view.tsx", {
    "./verification-types": types,
    "./shared": { Badge },
    "./verification-steps-table": { VerificationStepsTable: Table },
  });
  const item = {
    item_id: "case-item",
    title: "关联用例",
    case_version: 1,
    snapshot: { steps: current.steps },
    result: "pending",
    stale: false,
    latest_execution: null,
  };
  let selected;
  const cases = { ...current, mode: "cases", items: [item] };
  const live = VerificationRoundView({
    round: cases,
    onExecute: (...args) => {
      selected = args;
    },
  });
  descendants(live)
    .find((node) => node.type === Table)
    .props.onResultChange(1, "failed");
  assert.deepEqual(selected, [item, 1, "failed"]);
  const historical = VerificationRoundView({ round: { ...cases, can_record: false } });
  assert.equal(descendants(historical).find((node) => node.type === Table).props.onResultChange, undefined);
});

test("验证结果详情不显示环境等重复信息", () => {
  const html = renderRound();
  assert.doesNotMatch(html, />环境/);
  assert.doesNotMatch(html, />本地</);
});
