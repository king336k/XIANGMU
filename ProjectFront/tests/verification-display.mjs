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
  assert.equal(types.verificationStatus.waiting_repair, "等待修复");
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
  const menu = descendants(table).find((node) => node.props?.ariaLabel === "步骤 2 结果");
  assert.ok(menu, "使用不会截断文字的浮层菜单");
  assert.equal(menu.props.placement, "bottom-end");
  descendants(menu)
    .find((node) => node.key === "failed")
    .props.onClick();
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
    swr: { default: () => ({ data, mutate: async () => {} }), useSWRConfig: () => ({ mutate: async () => {} }) },
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
  assert.equal(views[0].props.onManualResultChange, undefined);
  assert.equal(views[1].props.onManualResultChange, undefined);
  descendants(render())
    .find((node) => node.props?.children === "填写测试结果")
    .props.onClick();
  data.current = { ...current, id: "next", version: 4, round_no: 2 };
  const form = descendants(render()).find((node) => node.type === Form);
  assert.equal(form.props.round.id, "current");
  assert.equal(form.props.round.version, 2);
  assert.equal(form.props.initialStepIndex, undefined);

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

test("缺陷验证进度显示当前阶段，并用颜色区分退回与完成", () => {
  const { VerificationProgress } = load("verification-progress.tsx");
  const value = {
    ...round,
    status: "returned_repair",
  };
  const html = renderToStaticMarkup(React.createElement(VerificationProgress, { round: value, defectStatus: "open" }));
  assert.match(html, /aria-label="缺陷验证进度"/);
  assert.match(html, /aria-current="step"[^>]*>.*退回修复/s);
  assert.match(html, /border-danger-subtle bg-danger-subtle text-danger-primary/);
  assert.match(html, /安排测试/);
  assert.match(html, /关闭缺陷/);
});

test("十条用例集中在同一轮列表，管理员代测后显示实际执行人及剩余项", () => {
  const items = Array.from({ length: 10 }, (_, index) => ({
    item_id: `item-${index}`,
    case_id: `case-${index}`,
    case_version: 1,
    revision_id: `revision-${index}`,
    source: "library",
    title: `检查 ${index + 1}`,
    snapshot: { steps: [{ action: "执行", expected: "通过" }] },
    stale: false,
    latest_execution:
      index === 0
        ? {
            id: "exec-admin",
            result: "passed",
            actual_result: "管理员代测通过",
            evidence: "",
            executor: "管理员",
            created_at: "2026-11-15T00:00:00Z",
            step_results: [],
          }
        : null,
    result: index === 0 ? "passed" : "pending",
  }));
  const html = renderRound({
    ...round,
    mode: "cases",
    items,
    summary: { total: 10, passed: 1, failed: 0, pending: 9, blocked: 0, inconclusive: 0, skipped: 0 },
  });
  assert.match(html, /共 10 条/);
  assert.match(html, /通过 1/);
  assert.match(html, /未执行 9/);
  assert.match(html, /管理员 ·/);
  assert.match(html, /管理员代测通过/);
  assert.equal((html.match(/检查 \d+/g) || []).length, 10);
});

test("用例执行表显示逐条测试备注并保留管理员实际执行人", () => {
  const { VerificationRoundView } = load("verification-round-view.tsx", {
    "./verification-types": types,
    "./shared": { Badge },
    "./verification-steps-table": { VerificationStepsTable: () => null },
  });
  const item = {
    item_id: "i1",
    title: "相机连接",
    case_version: 2,
    source: "library",
    snapshot: { steps: [] },
    result: "passed",
    stale: false,
    latest_execution: {
      id: "e1",
      result: "passed",
      actual_result: "相机连接正常",
      evidence: "管理员代执行，序列号已核对",
      executor: "管理员",
      created_at: "2026-11-15T01:00:00Z",
      step_results: [],
    },
    execution_history: [],
  };
  const value = {
    ...round,
    mode: "cases",
    status: "testing",
    execution_state: "running",
    items: [item],
    test_requirements: "检查相机连接",
    summary: { total: 1, passed: 1, failed: 0, pending: 0 },
    events: [],
  };
  const tree = VerificationRoundView({ round: value });
  const html = renderToStaticMarkup(React.createElement(() => tree));
  for (const text of [
    "执行验证",
    "用例执行列表",
    "测试要求",
    "通过 1",
    "测试结果：",
    "相机连接正常",
    "测试备注：管理员代执行，序列号已核对",
    "管理员",
  ]) {
    assert.ok(html.includes(text), text);
  }
});

test("提交单条用例结果时保留可选测试备注", async () => {
  const states = [];
  let cursor = 0;
  const writes = [];
  let requestSequence = 0;
  const Field = ({ label, children }) => React.createElement("label", null, label, children);
  const Modal = ({ children, ...props }) => React.createElement("div", { ...props, "data-modal": true }, children);
  const api = load("verification-case-execution.tsx", {
    react: {
      ...React,
      useState(initial) {
        const index = cursor++;
        if (!(index in states)) states[index] = typeof initial === "function" ? initial() : initial;
        return [states[index], (value) => (states[index] = value)];
      },
    },
    uuid: { v4: () => `execution-request-${++requestSequence}` },
    "./api": {
      qualityApi: {
        write: async (...args) => {
          writes.push(args);
          return { current: {} };
        },
      },
    },
    "./shared": { Field, Modal, fieldClass: "field" },
    "./types": {
      resultNames: { passed: "通过", failed: "失败", blocked: "阻塞", inconclusive: "无法判定", skipped: "跳过" },
      reasonNames: {},
    },
  });
  const item = {
    item_id: "item-1",
    title: "相机连接",
    snapshot: { steps: [{ action: "连接相机", expected: "连接成功" }] },
    latest_execution: { result: "passed", actual_result: "已连接", evidence: "旧备注" },
  };
  const render = () => {
    cursor = 0;
    return api.VerificationCaseExecution({
      base: "/quality/",
      item,
      round: { version: 3 },
      onSaved: async () => {},
      onClose: () => {},
    });
  };
  const first = descendants(render());
  const noteField = first.find((node) => node.type === "textarea" && node.props.value === "旧备注");
  assert.ok(noteField, "现有备注会回填到本条用例");
  noteField.props.onChange({ target: { value: "管理员代测：已核对设备状态" } });
  const modal = descendants(render()).find((node) => node.type === Modal);
  await modal.props.onSubmit({ get: () => "" });
  await modal.props.onSubmit({ get: () => "" });
  assert.equal(writes[0][0], "/quality/verification/cases/item-1/executions/");
  assert.equal(writes[0][1].evidence, "管理员代测：已核对设备状态");
  assert.equal(writes[0][1].actual_result, "已连接");
  assert.equal(writes[1][1].request_id, writes[0][1].request_id, "uncertain retries reuse one idempotency key");
});
