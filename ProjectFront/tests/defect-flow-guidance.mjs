import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const api = {};
new Function(
  "require",
  "exports",
  ts.transpileModule(
    readFileSync(new URL("../core/components/quality/defect-flow-guidance.tsx", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
  ).outputText
)((id) => {
  if (id === "./types") return { can: (context, key) => !!context.can_write && !!context.capabilities?.[key] };
  if (id === "./verification-types")
    return {
      verificationNextStep: (round) => (round.can_record ? "填写测试结果" : `等待 ${round.assignee_name} 测试`),
    };
  if (id === "react/jsx-runtime") return require(id);
  return {};
}, api);
const defect = { id: "d", status: "in_progress", assignee_id: "tech", assignee_name: "技术员", module: { key: "daq" } };
const context = (id, extra = {}) => ({ user_id: id, can_write: true, capabilities: {}, ...extra });
const data = (status, extra = {}) => ({
  defect_status: "in_progress",
  solution_review: { status, created_by_id: "tech", reviewer_ids: ["manager"] },
  current: null,
  ...extra,
});
test("五个流程节点跳转到对应页面", () => {
  for (const [stage, tab] of [
    [0, "overview"],
    [1, "diagnosis"],
    [2, "solution"],
    [3, "regression"],
    [4, "regression"],
  ])
    assert.equal(api.defectFlowTab(stage), tab);
  assert.equal(api.defectFlowTab(-1), undefined);
});
test("上报人等待分诊、经理可直达诊断分配", () => {
  const value = { ...defect, assignee_id: null, module: null };
  assert.equal(api.defectFlowStep(value, context("reporter"), data("missing")).action, undefined);
  assert.deepEqual(api.defectFlowStep(value, context("manager", { is_manager: true }), data("missing")).action, {
    tab: "diagnosis",
    label: "核对诊断与分配",
  });
});
test("技术员提交方案、指定经理审核、其他角色等待", () => {
  const tech = context("tech", { capabilities: { solution: true } });
  assert.equal(api.defectFlowStep(defect, tech, data("missing")).action.label, "填写修复方案");
  assert.equal(api.defectFlowStep(defect, tech, data("draft")).action.label, "编辑并提交方案");
  assert.equal(
    api.defectFlowStep(
      defect,
      context("manager", { is_manager: true, capabilities: { solution: true } }),
      data("draft")
    ).action,
    undefined
  );
  assert.equal(
    api.defectFlowStep(defect, context("manager", { is_manager: true, capabilities: { review: true } }), data("review"))
      .action.label,
    "审核修复方案"
  );
  assert.equal(
    api.defectFlowStep(
      defect,
      context("other-manager", { is_manager: true, capabilities: { review: true } }),
      data("review")
    ).action,
    undefined
  );
});
test("审核通过后按服务端权限交接测试，测试员执行，技术员等待", () => {
  assert.equal(
    api.defectFlowStep(defect, context("tech"), data("approved", { can_configure: true })).action.label,
    "修复并安排测试"
  );
  const row = { status: "testing", assignee_name: "测试员", can_record: true, can_configure: false };
  const state = data("approved", { defect_status: "resolved", current: row });
  assert.equal(
    api.defectFlowStep({ ...defect, status: "resolved" }, context("tester"), state).action.label,
    "执行回归测试"
  );
  const waiting = api.defectFlowStep({ ...defect, status: "resolved" }, context("tech"), {
    ...state,
    current: { ...row, can_record: false },
  });
  assert.equal(waiting.action, undefined);
  assert.equal(waiting.message, "等待 测试员 测试");
});
test("经理验收入口与测试员等待提示不同，关闭归档保留历史", () => {
  const current = { status: "review", can_return_test: true };
  const state = data("approved", { defect_status: "resolved", current });
  assert.equal(api.defectFlowStep(defect, context("manager"), state).action.label, "验收测试结果");
  assert.equal(
    api.defectFlowStep(defect, context("tester"), { ...state, current: { ...current, can_return_test: false } }).action,
    undefined
  );
  assert.equal(api.defectFlowStep({ ...defect, status: "closed" }, context("reporter"), state).stage, 5);
  assert.equal(api.defectFlowStep({ ...defect, archived_at: "today" }, context("manager"), state).action, undefined);
});

test("已投票的经理等待其他审核人，不重复显示审核操作", () => {
  const state = data("review");
  state.solution_review.pending_reviewer_ids = ["other-manager"];
  const result = api.defectFlowStep(
    defect,
    context("manager", { is_manager: true, capabilities: { review: true } }),
    state
  );
  assert.equal(result.action, undefined);
  assert.match(result.message, /等待指定/);
});

test("启用业务角色时未指派的项目经理不获得技术员填写方案入口", () => {
  const result = api.defectFlowStep(
    defect,
    context("manager", {
      is_manager: true,
      business_roles_enabled: true,
      capabilities: { solution: true },
    }),
    data("missing")
  );
  assert.equal(result.action, undefined);
});
