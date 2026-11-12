import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const nodes = (tree) =>
  !tree || typeof tree !== "object"
    ? []
    : Array.isArray(tree)
      ? tree.flatMap(nodes)
      : [tree, ...nodes(tree.props?.children)];
function harness(current = null, canConfigure = true) {
  const exp = {},
    states = [],
    writes = [],
    data = { defect_id: "d", defect_version: 7, defect_status: "resolved", current, history: [] };
  let index = 0;
  const stub = new Map();
  const sym = (key) => {
    if (!stub.has(key)) stub.set(key, () => null);
    return stub.get(key);
  };
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/quality/defect-verification-scope.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
    ).outputText
  )((id) => {
    if (id === "react")
      return {
        ...React,
        useEffect: () => {},
        useState: (initial) => {
          const n = index++;
          if (!(n in states)) states[n] = initial;
          return [states[n], (v) => (states[n] = v)];
        },
      };
    if (id === "react/jsx-runtime") return require(id);
    if (id === "swr") return { default: () => ({ data, mutate: async (v) => v }) };
    if (id === "./api")
      return {
        qualityApi: { write: async (...args) => writes.push(args), read: async () => ({ id: "d" }) },
        errorMessage: String,
      };
    if (id === "./types") return { can: () => canConfigure };
    return new Proxy({}, { get: (_, key) => (key === "fieldClass" ? "field" : sym(key)) });
  }, exp);
  return {
    writes,
    sym,
    replaceRound(next) {
      data.current = next;
      data.defect_version += 1;
    },
    render() {
      index = 0;
      return exp.DefectVerificationScope({
        base: "/q/",
        value: { id: "d", status: "resolved", edit_version: 7, fixed_build: "v2" },
        context: { can_write: true },
        onChanged: async () => {},
        projectUrl: "/p/",
      });
    },
  };
}
test("新缺陷未安排，直接选择两种方式，不默认选人工", () => {
  const h = harness(),
    tree = h.render(),
    all = nodes(tree);
  assert.ok(all.some((n) => n.props?.children === "尚未安排"));
  for (const label of ["人工验证", "用例回归"]) assert.ok(all.some((n) => n.props?.children === label));
  assert.equal(
    all.some((n) => n.type === h.sym("VerificationConfigure")),
    false
  );
  all.find((n) => n.props?.children === "用例回归").props.onClick();
  const editor = nodes(h.render()).find((n) => n.type === h.sym("VerificationConfigure"));
  assert.equal(editor.props.initialMode, "cases");
});
test("已安排可修改，传递当前轮和最新缺陷版本", () => {
  const round = { id: "r", mode: "cases", version: 4, round_no: 2, can_configure: true };
  const h = harness(round);
  nodes(h.render())
    .find((n) => n.props?.children === "修改安排")
    .props.onClick();
  const editor = nodes(h.render()).find((n) => n.type === h.sym("VerificationConfigure"));
  assert.deepEqual(editor.props.initial, round);
  assert.equal(editor.props.version, 7);
});
test("无配置权限用户不显示安排入口", () => {
  const h = harness(null, false),
    all = nodes(h.render());
  assert.ok(all.some((n) => n.props?.children === "尚未安排"));
  assert.equal(
    all.some((n) => ["人工验证", "用例回归"].includes(n.props?.children)),
    false
  );
});

test("退回修复后重新修复明确提示旧结果，重新安排沿用当前修复版本", () => {
  const round = {
    id: "r",
    mode: "manual",
    status: "returned_repair",
    version: 2,
    round_no: 1,
    fixed_build: "old",
    can_configure: true,
  };
  const h = harness(round),
    all = nodes(h.render());
  assert.ok(all.some((n) => n.props?.label === "待重新安排"));
  all.find((n) => n.props?.children === "重新安排").props.onClick();
  const editor = nodes(h.render()).find((n) => n.type === h.sym("VerificationConfigure"));
  assert.equal(editor.props.initial.fixed_build, "v2");
});
test("经理可查看失败结果并退回，失败轮次的验收关闭按钮禁用", () => {
  const round = {
    id: "r",
    mode: "cases",
    status: "review",
    version: 2,
    round_no: 1,
    can_accept: false,
    can_return_test: true,
    can_return_repair: true,
    summary: { passed: 1, total: 2, pending: 0, failed: 1 },
  };
  const h = harness(round),
    all = nodes(h.render());
  assert.equal(all.find((n) => n.props?.children === "验收关闭").props.disabled, true);
  assert.ok(all.find((n) => n.props?.children === "退回修复"));
  assert.ok(all.find((n) => n.props?.children === "退回补测"));
});

test("打开人工记录后刷新到新轮次，表单仍指向原轮次快照", () => {
  const old = {
    id: "old",
    mode: "manual",
    status: "testing",
    version: 2,
    round_no: 1,
    fixed_build: "v2",
    environment: "环境A",
    can_record: true,
    summary: { total: 1, passed: 0, pending: 1 },
    steps: [{ action: "旧操作", expected: "旧预期" }],
  };
  const h = harness(old);
  nodes(h.render())
    .find((n) => n.props?.children === "记录结果")
    .props.onClick();
  const first = nodes(h.render()).find((n) => n.type === h.sym("VerificationManualResult"));
  assert.equal(first.props.round.id, "old");
  h.replaceRound({
    ...old,
    id: "new",
    version: 3,
    round_no: 2,
    fixed_build: "v3",
    environment: "环境B",
    steps: [{ action: "新操作", expected: "新预期" }],
  });
  const refreshed = nodes(h.render()).find((n) => n.type === h.sym("VerificationManualResult"));
  assert.ok(refreshed, "刷新时保留原草稿表单");
  assert.equal(refreshed.props.round.id, "old");
  assert.equal(refreshed.props.round.version, 2);
  assert.equal(refreshed.props.round.fixed_build, "v2");
});

test("验收确认框打开后新轮次替换，提交仍使用原轮次expected_version", async () => {
  const old = {
    id: "old",
    mode: "cases",
    status: "review",
    version: 2,
    round_no: 1,
    fixed_build: "v2",
    can_accept: true,
    can_return_test: true,
    summary: { total: 1, passed: 1, pending: 0 },
  };
  const h = harness(old);
  nodes(h.render())
    .find((n) => n.props?.children === "验收关闭")
    .props.onClick();
  h.replaceRound({ ...old, id: "new", version: 5, round_no: 2, fixed_build: "v3" });
  const modal = nodes(h.render()).find((n) => n.type === h.sym("Modal") && n.props.title === "验收关闭");
  assert.ok(modal);
  await modal.props.onSubmit(new Map([["comment", "已核对v2"]]));
  assert.equal(h.writes[0][0], "/q/defects/d/verification/workflow/");
  assert.equal(h.writes[0][1].expected_version, 2);
  assert.equal(h.writes[0][1].action, "accept");
});

test("打开关联用例执行后新轮次替换，执行上下文仍绑定原用例和修复版本", () => {
  const item = {
    item_id: "item-old",
    title: "旧用例",
    case_version: 1,
    snapshot: { steps: [{ action: "旧操作", expected: "旧预期" }] },
  };
  const old = {
    id: "old",
    mode: "cases",
    status: "testing",
    version: 2,
    round_no: 1,
    fixed_build: "v2",
    environment: "环境A",
    can_record: true,
    summary: { total: 1, passed: 0, pending: 1 },
  };
  const h = harness(old);
  nodes(h.render())
    .find((n) => n.type === h.sym("VerificationRoundView"))
    .props.onExecute(item);
  h.replaceRound({ ...old, id: "new", version: 3, round_no: 2, fixed_build: "v3", environment: "环境B" });
  const execution = nodes(h.render()).find((n) => n.type === h.sym("ExecutionForm"));
  assert.ok(execution);
  assert.equal(execution.props.item.id, "item-old");
  assert.equal(execution.props.plan.build, "v2");
  assert.equal(execution.props.plan.environment, "环境A");
  assert.match(execution.props.plan.name, /1/);
});
