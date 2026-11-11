import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const React = require("react");
const components = new Map();
function stub(name) {
  if (!components.has(name)) components.set(name, () => null);
  return components.get(name);
}
function load(name, writes = []) {
  const exports = {};
  const code = ts.transpileModule(
    readFileSync(new URL(`../core/components/quality/${name}.tsx`, import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }
  ).outputText;
  new Function("require", "exports", code)((id) => {
    if (id === "react")
      return {
        ...React,
        useState: (value) => [typeof value === "function" ? value() : value, () => {}],
        useMemo: (fn) => fn(),
      };
    if (id === "react/jsx-runtime") return require(id);
    if (id === "swr") return { default: () => ({ mutate: async () => {} }) };
    if (id === "./types")
      return {
        can: (context, key) => context.can_write && context.capabilities?.[key] === true,
        planStatusNames: {},
        resultNames: { passed: "通过" },
        reasonNames: {},
      };
    if (id === "./api") return { qualityApi: { write: async (...args) => writes.push(args) }, errorMessage: String };
    return new Proxy({}, { get: (_, key) => (key === "fieldClass" ? "field" : stub(String(key))) });
  }, exports);
  return exports;
}
function nodes(tree) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
const labels = (tree) =>
  nodes(tree)
    .filter((node) => node.type === stub("Button"))
    .map((node) => node.props.children);
const ctx = (role, own = false, execute = true, extra = {}) => ({
  user_id: own ? "assigned" : "actor",
  is_manager: role === "PROJECT_MANAGER" || role === "PLATFORM_ADMIN",
  business_role: role,
  business_roles: [role],
  business_roles_enabled: true,
  can_write: true,
  capabilities: { execute },
  members: [],
  ...extra,
});
const item = {
  id: "item1",
  revision: { title: "用例", version: 1, snapshot: { steps: [], preconditions: "", module: "" } },
  latest_execution: null,
};
const plan = (status) => ({
  id: "plan1",
  managed: true,
  status,
  assignee_id: "assigned",
  workflow_version: 3,
  round_no: 1,
  summary: { total: 1, passed: 1, inconclusive: 0 },
  workflow_events: [],
  items: [item],
  data_regression: { task_id: 7, round_started_at: "2026-11-10T00:00:00Z", request_snapshot: {} },
});
function workflow(context, status, writes = []) {
  return load("workflow-panel", writes).PlanWorkflowPanel({
    base: "/q/",
    plan: plan(status),
    context,
    onSaved: async () => {},
  });
}
for (const [status, expected] of [
  ["ready", ["认领并开始"]],
  ["running", ["暂停测试", "提交测试结果"]],
  ["paused", ["恢复测试"]],
]) {
  test(`管理员可代操作他人${status}计划`, () => {
    for (const context of [
      ctx("PLATFORM_ADMIN"),
      ctx("PLATFORM_ADMIN", false, true, { business_roles: [] }),
      ctx("PLATFORM_ADMIN", false, true, { business_roles: undefined }),
      ctx(null, false, true, { business_roles: ["REGRESSION_TESTER", "PLATFORM_ADMIN"] }),
    ])
      for (const label of expected) assert.ok(labels(workflow(context, status)).includes(label), label);
  });
}
test("管理员代操作仍尊重execute能力和状态机", () => {
  for (const [context, status] of [
    [ctx("PLATFORM_ADMIN", false, false), "running"],
    [ctx("PLATFORM_ADMIN"), "completed"],
    [ctx("PLATFORM_ADMIN"), "review"],
  ])
    for (const label of ["认领并开始", "暂停测试", "恢复测试", "提交测试结果"])
      assert.ok(!labels(workflow(context, status)).includes(label));
  const review = { ...plan("review"), summary: { ...plan("review").summary, inconclusive: 1 } };
  assert.ok(
    !labels(
      load("workflow-panel").PlanWorkflowPanel({
        base: "/q/",
        plan: review,
        context: ctx("PLATFORM_ADMIN"),
        onSaved: async () => {},
      })
    ).includes("确认测试结果")
  );
});
test("普通经理不因is_manager获得执行，普通岗位仍只操作本人计划", () => {
  assert.ok(!labels(workflow(ctx("PROJECT_MANAGER", false, false), "running")).includes("提交测试结果"));
  for (const role of ["TECHNICIAN", "REGRESSION_TESTER"])
    for (const own of [false, true])
      assert.equal(labels(workflow(ctx(role, own), "running")).includes("提交测试结果"), own);
});
for (const [file, exportName, label] of [["plan-detail", "PlanDetail", "执行用例"]])
  test(`${label}允许管理员代操作但不放宽运行状态和普通岗位归属`, () => {
    const Component = load(file)[exportName];
    for (const [context, status, canWrite, expected] of [
      [ctx("PLATFORM_ADMIN"), "running", true, true],
      [ctx("PLATFORM_ADMIN"), "paused", true, false],
      [ctx("PLATFORM_ADMIN", false, false), "running", false, false],
      [ctx("PROJECT_MANAGER", false, false), "running", false, false],
      [ctx("REGRESSION_TESTER"), "running", true, false],
      [ctx("REGRESSION_TESTER", true), "running", true, true],
    ]) {
      const value = plan(status);
      const tree = Component({ base: "/q/", value, plan: value, context, canWrite, onSaved: async () => {} });
      assert.equal(labels(tree).includes(label), expected, `${context.business_role}/${status}`);
    }
  });
test("代操作请求保留真实actor语义且不隐式改负责人", async () => {
  const writes = [];
  const tree = workflow(ctx("PLATFORM_ADMIN"), "running", writes);
  await nodes(tree)
    .find((node) => node.type === stub("Button") && node.props.children === "暂停测试")
    .props.onClick();
  assert.deepEqual(writes[0], ["/q/plans/plan1/workflow/", { action: "pause", expected_version: 3 }]);
  const form = load("execution-form", writes).ExecutionForm({
    base: "/q/",
    plan: plan("running"),
    item,
    onSaved: async () => {},
  });
  await form.props.onSubmit(new FormData());
  assert.ok(!("assignee_id" in writes[1][1]) && !("executor" in writes[1][1]));
});
