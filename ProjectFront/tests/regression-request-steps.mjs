import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
function harness() {
  const state = [true, []],
    exports = {};
  let index = 0;
  const writes = [];
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/quality/data-regression-panel.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
    ).outputText
  )((id) => {
    if (id === "react")
      return {
        ...React,
        useState: () => {
          const key = index++;
          return [state[key], (value) => (state[key] = value)];
        },
      };
    if (id === "swr") return { default: () => ({ data: [], mutate: async () => {} }) };
    if (id === "./api") return { qualityApi: { write: async (...args) => writes.push(args) }, errorMessage: String };
    if (id === "./types") return { can: () => true, planStatusNames: {} };
    if (id === "./shared") return { Modal: "modal", Field: "field", fieldClass: "field" };
    if (id === "./paged-record-select") return { PagedRecordSelect: "select" };
    if (id === "@/components/common/project-route-link") return { ProjectRouteLink: "a" };
    if (id === "@plane/ui") return { Button: "button" };
    if (id === "@plane/utils") return {};
    return require(id);
  }, exports);
  const render = () => {
    index = 0;
    return exports.DataRegressionPanel({
      base: "/q/",
      projectUrl: "/p/",
      defect: { id: "d", status: "resolved" },
      context: { is_manager: true },
    });
  };
  const nodes = (node) =>
    node && typeof node === "object" ? [node, ...React.Children.toArray(node.props?.children).flatMap(nodes)] : [];
  return { state, writes, render, nodes };
}
test("删除验证步骤保留下一行身份，保存仅提交操作与预期", async () => {
  const h = harness();
  for (let i = 0; i < 3; i++)
    h.nodes(h.render())
      .find((n) => n.type === "button" && n.props.children === "添加验证步骤")
      .props.onClick();
  const keys = h
    .nodes(h.render())
    .filter((n) => n.type === "div" && n.props.className === "space-y-2 rounded border border-subtle p-3")
    .map((n) => n.key);
  assert.equal(new Set(keys).size, 3);
  const original = h.state[1][1];
  h.nodes(h.render())
    .find((n) => n.type === "button" && n.props.children === "移除此步骤")
    .props.onClick();
  const after = h
    .nodes(h.render())
    .filter((n) => n.type === "div" && n.props.className === "space-y-2 rounded border border-subtle p-3")
    .map((n) => n.key);
  assert.deepEqual(after, keys.slice(1));
  assert.equal(h.state[1][0], original);
  h.state[1] = h.state[1].map((row) => ({ ...row, action: "检查连接", expected: "正常" }));
  const modal = h.nodes(h.render()).find((n) => n.type === "modal");
  await modal.props.onSubmit(
    new Map([
      ["solution_id", "s"],
      ["environment", "x"],
      ["test_target", "目标"],
    ])
  );
  assert.deepEqual(h.writes[0][1].verification_steps, [
    { action: "检查连接", expected: "正常" },
    { action: "检查连接", expected: "正常" },
  ]);
});
