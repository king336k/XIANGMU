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
    .find((n) => n.props?.children === "修改")
    .props.onClick();
  const editor = nodes(h.render()).find((n) => n.type === h.sym("VerificationConfigure"));
  assert.equal(editor.props.initial, round);
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
