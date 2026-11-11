import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
function harness(manager = true, dataRequired = true, manual = false) {
  const state = [false, false];
  let index = 0;
  const writes = [],
    changed = [],
    exports = {};
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
        useState: () => {
          const key = index++;
          return [
            state[key],
            (value) => {
              state[key] = value;
            },
          ];
        },
      };
    if (id === "./api")
      return {
        qualityApi: {
          write: async (...args) => {
            writes.push(args);
            return { id: "d", requires_data_regression: false };
          },
        },
      };
    if (id === "./shared") return { Field: "field", Modal: "modal", fieldClass: "field" };
    return require(id);
  }, exports);
  const props = {
    base: "/q/",
    value: {
      id: "d",
      status: "resolved",
      edit_version: 7,
      requires_data_regression: dataRequired,
      manual_verification_allowed: manual,
    },
    context: { is_manager: manager },
    onChanged: async (value) => {
      changed.push(value);
    },
  };
  const render = () => {
    index = 0;
    return exports.DefectVerificationScope(props);
  };
  const nodes = (node) =>
    node && typeof node === "object" ? [node, ...React.Children.toArray(node.props?.children).flatMap(nodes)] : [];
  return { render, nodes, writes, changed };
}
test("验证方式只提供功能和数据两种；提交原版本和简短原因", async () => {
  const h = harness();
  h.nodes(h.render())
    .find((n) => n.type === "button")
    .props.onClick();
  const nodes = h.nodes(h.render());
  assert.deepEqual(
    nodes.filter((n) => n.type === "option").map((n) => n.props.children),
    ["功能验证", "数据验证"]
  );
  await nodes
    .find((n) => n.type === "modal")
    .props.onSubmit(
      new Map([
        ["verification_scope", "functional"],
        ["reason", "只调整提示"],
      ])
    );
  assert.deepEqual(h.writes, [
    [
      "/q/defects/d/",
      { expected_version: 7, verification_scope: "functional", verification_scope_reason: "只调整提示" },
      "patch",
    ],
  ]);
  assert.equal(h.changed[0].requires_data_regression, false);
  assert.equal(
    h.nodes(h.render()).some((n) => n.type === "modal"),
    false
  );
});
test("技术员不显示调整验证方式入口", () => {
  const h = harness(false, false);
  assert.equal(h.nodes(h.render()).filter((n) => n.type === "button").length, 0);
});

test("普通缺陷验证关闭只填写验证结果，不要求Session或数据包", async () => {
  const h = harness(true, false, true);
  h.nodes(h.render())
    .find((n) => n.type === "button" && n.props.children === "验证并关闭")
    .props.onClick();
  const modal = h.nodes(h.render()).find((n) => n.type === "modal");
  assert.equal(h.nodes(modal).filter((n) => n.type === "textarea").length, 1);
  await modal.props.onSubmit(new Map([["result", "测试员确认新版本提示正确，经理复核"]]));
  assert.deepEqual(h.writes[0], [
    "/q/defects/d/",
    {
      expected_version: 7,
      status: "closed",
      verification_method: "manual",
      verification_note: "测试员确认新版本提示正确，经理复核",
    },
    "patch",
  ]);
});
