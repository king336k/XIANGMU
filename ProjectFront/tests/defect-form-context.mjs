import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
const require = createRequire(new URL("../package.json", import.meta.url));
const React = require("react"),
  ts = require("typescript");
const Detail = () => null,
  Modal = () => null;
const nodes = (tree) =>
  !tree || typeof tree !== "object"
    ? []
    : Array.isArray(tree)
      ? tree.flatMap(nodes)
      : [tree, ...nodes(tree.props?.children)];
test("登记修复与取消保留当前缺陷详情，保存后留在该缺陷而非返回列表", async () => {
  const state = [],
    exports = {};
  let cursor = 0,
    closed = 0;
  const original = { id: "defect-258", code: "BASEKNOW-D-258", title: "现场异常", status: "open", edit_version: 3 };
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL("../core/components/quality/defect-form.tsx", import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((id) => {
    if (id === "react")
      return {
        ...React,
        useRef: (value) => ({ current: value }),
        useState: (initial) => {
          const i = cursor++;
          if (!(i in state)) state[i] = typeof initial === "function" ? initial() : initial;
          return [
            state[i],
            (value) => {
              state[i] = value;
            },
          ];
        },
      };
    if (id === "react/jsx-runtime") return require(id);
    if (id === "swr") return { default: () => ({ data: [] }) };
    if (id === "./defect-detail") return { DefectDetail: Detail };
    if (id === "./shared") return { Modal, Field: () => null, fieldClass: "", Badge: () => null };
    if (id === "./types")
      return { can: () => true, statusNames: { open: "待处理", resolved: "待回归" }, severityNames: {} };
    if (id === "./api")
      return {
        qualityApi: { write: async () => ({ ...original, status: "resolved", edit_version: 4, fixed_build: "v2" }) },
      };
    if (id === "./defect-attachments") return { uploadDefectFiles: async () => {} };
    return new Proxy({}, { get: () => () => null });
  }, exports);
  const render = () => {
    cursor = 0;
    return exports.DefectForm({
      base: "/q/",
      context: { members: [], issues: [], is_manager: true },
      value: original,
      onClose: () => closed++,
      onSaved: async () => {},
      projectUrl: "/p/",
    });
  };
  const detail = nodes(render()).find((n) => n.type === Detail);
  detail.props.onEdit("workflow");
  let tree = render();
  assert.ok(
    nodes(tree).some((n) => n.type === Detail),
    "修复弹窗打开时当前详情仍挂载，回归标签不丢失"
  );
  let modal = nodes(tree).find((n) => n.type === Modal);
  modal.props.onClose();
  assert.equal(closed, 0, "取消返回同一缺陷");
  nodes(render())
    .find((n) => n.type === Detail)
    .props.onEdit("workflow");
  modal = nodes(render()).find((n) => n.type === Modal);
  await modal.props.onSubmit(new FormData());
  modal.props.onClose();
  tree = render();
  assert.equal(closed, 0, "保存不会关闭整个缺陷");
  const updated = nodes(tree).find((n) => n.type === Detail);
  assert.equal(updated.props.value.id, original.id);
  assert.equal(updated.props.value.status, "resolved");
  assert.equal(updated.props.value.edit_version, 4);
});
