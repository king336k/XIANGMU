import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url));
const React = require("react"),
  ts = require("typescript");
function harness(current) {
  const states = [],
    writes = [],
    stubs = new Map();
  let cursor = 0;
  const component = (name) => {
    if (!stubs.has(name)) stubs.set(name, () => null);
    return stubs.get(name);
  };
  const exp = {},
    data = { current };
  const source = readFileSync(new URL("../core/components/quality/verification-assignee.tsx", import.meta.url), "utf8");
  new Function(
    "require",
    "exports",
    ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } })
      .outputText
  )((id) => {
    if (id === "react")
      return {
        ...React,
        useState: (initial) => {
          const i = cursor++;
          if (!(i in states)) states[i] = initial;
          return [states[i], (v) => (states[i] = v)];
        },
      };
    if (id === "react/jsx-runtime") return require(id);
    if (id === "swr")
      return {
        default: () => ({
          data,
          mutate: async (next) => {
            data.current = next.current;
          },
        }),
        useSWRConfig: () => ({ mutate: async () => {} }),
      };
    if (id === "./api")
      return {
        qualityApi: {
          write: async (...args) => {
            writes.push(args);
            return { current: { ...data.current, assignee_id: "tester2" } };
          },
        },
      };
    if (id === "./types") return { can: () => true };
    if (id === "uuid") return { v4: () => "request-test" };
    return new Proxy({}, { get: (_, name) => component(name) });
  }, exp);
  return {
    writes,
    component,
    render() {
      cursor = 0;
      return exp.VerificationAssignee({
        base: "/q/",
        defectId: "d",
        context: {
          members: [
            { id: "tester", name: "测试员", business_role: "REGRESSION_TESTER" },
            { id: "tech", name: "模块技术负责人", business_role: "TECHNICIAN" },
          ],
          business_roles_enabled: true,
        },
        onArrange() {},
      });
    },
  };
}
const nodes = (tree) =>
  !tree || typeof tree !== "object"
    ? []
    : Array.isArray(tree)
      ? tree.flatMap(nodes)
      : [tree, ...nodes(tree.props?.children)];
test("缺陷属性测试指派独立于模块责任，只选择本项目测试员", async () => {
  const h = harness({ version: 7, assignee_id: "tester", assignee_name: "测试员", can_configure: true });
  const all = nodes(h.render());
  assert.ok(all.some((n) => n.props?.children === "测试"));
  all.find((n) => n.props?.children === "修改指派").props.onClick();
  const next = nodes(h.render()),
    options = next.filter((n) => n.type === "option");
  assert.ok(options.some((n) => n.props.value === "tester"));
  assert.ok(!options.some((n) => n.props.value === "tech"));
  await next.find((n) => n.type === h.component("Modal")).props.onSubmit(new Map([["assignee_id", "tester2"]]));
  assert.equal(h.writes[0][0], "/q/defects/d/verification/workflow/");
  assert.deepEqual(h.writes[0][1], {
    action: "assign",
    expected_version: 7,
    request_id: "request-test",
    assignee_id: "tester2",
  });
});
test("提交验收后不再显示修改指派，未安排时有明确入口", () => {
  assert.ok(
    !nodes(harness({ can_configure: false, assignee_name: "测试员" }).render()).some(
      (n) => n.props?.children === "修改指派"
    )
  );
  const none = nodes(harness(null).render());
  assert.ok(none.some((n) => n.props?.children === "未安排"));
  assert.ok(none.some((n) => n.props?.children === "安排测试"));
});
