import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
const nodes = (t) =>
  !t || typeof t !== "object" ? [] : Array.isArray(t) ? t.flatMap(nodes) : [t, ...nodes(t.props?.children)];
function harness(file, name, props) {
  const api = {},
    states = [],
    writes = [],
    saved = [];
  let at = 0;
  const stubs = new Map(),
    stub = (n) => {
      if (!stubs.has(n)) stubs.set(n, () => null);
      return stubs.get(n);
    };
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(`../core/components/quality/${file}.tsx`, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((id) => {
    if (id === "react")
      return {
        ...React,
        useMemo: (fn) => fn(),
        useState: (initial) => {
          const index = at++;
          if (!(index in states)) states[index] = typeof initial === "function" ? initial() : initial;
          return [states[index], (v) => (states[index] = typeof v === "function" ? v(states[index]) : v)];
        },
      };
    if (id === "react/jsx-runtime" || id === "uuid") return require(id);
    if (id === "./api")
      return {
        qualityApi: {
          write: async (...args) => {
            writes.push(args);
            return { current: { id: "new" } };
          },
        },
        errorMessage: String,
      };
    if (id === "./types")
      return {
        resultNames: {
          passed: "通过",
          failed: "失败",
          blocked: "受阻",
          inconclusive: "无法判定",
          skipped: "跳过",
          pending: "未执行",
        },
        reasonNames: { environment: "环境", other: "其他" },
      };
    return new Proxy({}, { get: (_, key) => (key === "fieldClass" ? "field" : stub(key)) });
  }, api);
  return {
    states,
    writes,
    saved,
    stub,
    render(overrides = {}) {
      at = 0;
      if (props.round) props = { ...props, round: { manual_results: [], ...props.round } };
      return api[name]({
        ...props,
        ...overrides,
        onSaved: async (data) => saved.push(data),
        onCancel() {},
        onClose() {},
      });
    },
  };
}
test("人工验证安排只填写如何测试和版本，不再要求重复填写每一步预期", async () => {
  const h = harness("verification-configure", "VerificationConfigure", {
    base: "/q/",
    defectId: "d",
    version: 7,
    fixedBuild: "v2",
    initialMode: "manual",
  });
  let tree = h.render();
  nodes(tree)
    .find((n) => n.props?.label === "验证环境")
    .props.children.props.onChange({ target: { value: "195" } });
  tree = h.render();
  nodes(tree)
    .find((n) => n.props?.label === "如何测试")
    .props.children.props.onChange({ target: { value: "打开控制页" } });
  tree = h.render();
  const save = nodes(tree).find((n) => n.props?.children === "保存安排");
  assert.equal(save.props.disabled, false);
  save.props.onClick();
  await new Promise(setImmediate);
  assert.equal(h.writes[0][0], "/q/defects/d/verification/");
  assert.equal(h.writes[0][1].expected_version, 7);
  assert.deepEqual(h.writes[0][1].steps, [{ action: "打开控制页", expected: "" }]);
  assert.equal("case_id" in h.writes[0][1], false);
});
test("用例回归一次多选，发送本缺陷安排且当前方式明确选中", async () => {
  const h = harness("verification-configure", "VerificationConfigure", {
    base: "/q/",
    defectId: "d",
    version: 3,
    fixedBuild: "v3",
    initialMode: "cases",
  });
  let tree = h.render();
  assert.equal(nodes(tree).find((n) => n.type === "button" && n.props["aria-pressed"]).props.children[1], "用例回归");
  nodes(tree)
    .find((n) => n.type === h.stub("CasePicker"))
    .props.onChange([
      { id: "c1", title: "用例1" },
      { id: "c2", title: "用例2" },
    ]);
  tree = h.render();
  nodes(tree)
    .find((n) => n.props?.label === "验证环境")
    .props.children.props.onChange({ target: { value: "现场" } });
  tree = h.render();
  nodes(tree)
    .find((n) => n.props?.children === "保存安排")
    .props.onClick();
  await new Promise(setImmediate);
  assert.deepEqual(h.writes[0][1].case_ids, ["c1", "c2"]);
  assert.equal(h.writes[0][1].mode, "cases");
});
test("人工实际验证独立提交本轮结果，不直接关闭或要求采集Session", async () => {
  const h = harness("verification-manual-result", "VerificationManualResult", {
    base: "/q/",
    defectId: "d",
    round: { version: 5, fixed_build: "v2", environment: "现场", steps: [{ action: "启动", expected: "成功" }] },
  });
  const tree = h.render();
  nodes(tree)
    .find((node) => node.type === "textarea")
    .props.onChange({ target: { value: "启动成功" } });
  const updated = h.render();
  await updated.props.onSubmit(new Map([["result", "passed"]]));
  assert.equal(h.writes[0][0], "/q/defects/d/verification/result/");
  assert.equal(h.writes[0][1].expected_version, 5);
  assert.equal("status" in h.writes[0][1], false);
  assert.deepEqual(h.writes[0][1].step_results, [{ result: "passed", actual: "启动成功" }]);
});

test("人工实测同轮次收到等值新步骤数组时保持版本快照", () => {
  const round = {
    id: "round-1",
    version: 5,
    fixed_build: "v2",
    environment: "现场",
    steps: [{ action: "启动", expected: "成功" }],
  };
  const h = harness("verification-manual-result", "VerificationManualResult", { base: "/q/", defectId: "d", round });
  const first = h.render();
  const firstResult = nodes(first).find((node) => node.type === "select" && node.props.name === "result");
  const refreshed = h.render({ round: structuredClone(round) });
  const refreshedResult = nodes(refreshed).find((node) => node.type === "select" && node.props.name === "result");
  assert.equal(firstResult.props.value, "");
  assert.equal(refreshedResult.props.value, "");
  assert.equal(nodes(refreshed).find((node) => node.type === "p")?.props.children[0], "v2");
});

for (const inconclusiveAt of ["result"]) {
  test("人工实测无法判定提供原因和下一步并提交完整payload", async () => {
    const h = harness("verification-manual-result", "VerificationManualResult", {
      base: "/q/",
      defectId: "d",
      round: {
        id: "round-1",
        version: 5,
        fixed_build: "v2",
        environment: "现场",
        steps: [{ action: "启动", expected: "成功" }],
      },
    });
    let tree = h.render();
    const resultSelect = nodes(tree).find((node) => node.type === "select" && node.props.name === "result");
    assert.ok(!nodes(resultSelect).some((node) => node.type === "option" && node.props.value === "pending"));
    assert.equal(
      nodes(tree).some((node) => node.props?.name === "reason_category"),
      false
    );
    nodes(tree)
      .find((node) => node.type === "select" && node.props.name === inconclusiveAt)
      .props.onChange({ target: { value: "inconclusive" } });
    tree = h.render();
    assert.equal(nodes(tree).find((node) => node.props?.name === "reason_category").props.required, true);
    assert.equal(nodes(tree).find((node) => node.props?.name === "next_action").props.required, true);
    const payload = new Map([
      ["result", "inconclusive"],
      ["actual_result", "环境待处理，当前无法判定"],
      ["evidence", "现场日志"],
      ["actual_0", "网络不通"],
      ["reason_category", "environment"],
      ["next_action", "恢复环境后复测"],
    ]);
    nodes(tree)
      .find((node) => node.type === "textarea")
      .props.onChange({ target: { value: "环境待处理，当前无法判定" } });
    tree = h.render();
    await tree.props.onSubmit(payload);
    assert.equal(h.writes[0][0], "/q/defects/d/verification/result/");
    assert.equal(h.writes[0][1].reason_category, "environment");
    assert.equal(h.writes[0][1].next_action, "恢复环境后复测");
    assert.deepEqual(h.writes[0][1].step_results, [{ result: "inconclusive", actual: "环境待处理，当前无法判定" }]);
    assert.equal(h.writes[0][1].expected_version, 5);
  });
}

test("人工实测挂载后收到新轮次也只提交原版本，旧草稿不能归入新轮", async () => {
  const old = {
    id: "round-old",
    version: 2,
    fixed_build: "v2",
    environment: "环境A",
    steps: [{ action: "旧操作", expected: "旧预期" }],
  };
  const h = harness("verification-manual-result", "VerificationManualResult", {
    base: "/q/",
    defectId: "d",
    round: old,
  });
  h.render();
  const tree = h.render({
    round: {
      ...old,
      id: "round-new",
      version: 3,
      fixed_build: "v3",
      environment: "环境B",
      steps: [{ action: "新操作", expected: "新预期" }],
    },
  });
  nodes(tree)
    .find((node) => node.type === "textarea")
    .props.onChange({ target: { value: "仅验证旧版本" } });
  const updated = h.render({
    round: {
      ...old,
      id: "round-new",
      version: 3,
      fixed_build: "v3",
      environment: "环境B",
      steps: [{ action: "新操作", expected: "新预期" }],
    },
  });
  await updated.props.onSubmit(new Map([["result", "passed"]]));
  assert.equal(h.writes[0][1].expected_version, 2);
  assert.equal(h.writes[0][1].actual_result, "仅验证旧版本");
  const text = new Set(
    nodes(tree)
      .flatMap((n) => (Array.isArray(n.props?.children) ? n.props.children : [n.props?.children]))
      .filter((value) => typeof value === "string")
  );
  assert.ok(text.has("v2"));
  assert.ok(!text.has("v3"));
});

test("人工记录只填写简要测试结果，不重复填写证据和逐步结果", async () => {
  const h = harness("verification-manual-result", "VerificationManualResult", {
    base: "/q/",
    defectId: "d",
    round: { version: 2, fixed_build: "v2", environment: "旧环境", steps: [{ action: "启动", expected: "正常" }] },
  });
  const tree = h.render(),
    all = nodes(tree);
  assert.equal(
    all.some((n) => ["actual_result", "evidence"].includes(n.props?.name)),
    false
  );
  nodes(tree)
    .find((node) => node.type === "textarea")
    .props.onChange({ target: { value: "正常" } });
  const updated = h.render();
  await updated.props.onSubmit(new Map([["result", "passed"]]));
  assert.equal(h.writes[0][1].evidence, "");
  assert.deepEqual(h.writes[0][1].step_results, [{ result: "passed", actual: "正常" }]);
});
