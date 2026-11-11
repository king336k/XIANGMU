import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
const code = ts.transpileModule(
  readFileSync(new URL("../core/components/quality/requirement-state.tsx", import.meta.url), "utf8"),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
).outputText;
function load({ status = "draft", manager = true, next = "review", version = 4 } = {}) {
  const exports = {},
    writes = [];
  new Function("require", "exports", code)((id) => {
    if (id === "react") return { useState: () => [next, () => {}] };
    if (id === "./types") return { can: () => true };
    if (id === "./api") return { qualityApi: { write: async (...args) => writes.push(args) } };
    if (id === "./shared") return { Modal: () => null, Field: () => null, fieldClass: "" };
    return require(id);
  }, exports);
  return {
    ...exports,
    writes,
    tree: exports.RequirementState({
      base: "/q/",
      value: { id: "r", title: "需求A", status, version },
      context: { is_manager: manager },
      onClose() {},
      onSaved: async () => {},
    }),
  };
}
test("需求状态标签与合法流转一致，不能跳过审核和验收条件", async () => {
  const { requirementStatuses, requirementTransitions, tree, writes } = load();
  assert.deepEqual(Object.values(requirementStatuses), ["待完善", "待审核", "已确认", "验收完成", "已取消", "已归档"]);
  assert.equal(requirementTransitions("draft", true).completed, undefined);
  assert.equal(requirementTransitions("approved", false).completed, undefined);
  assert.equal(requirementTransitions("review", true).approved, "approve");
  const form = new FormData();
  await tree.props.onSubmit(form);
  assert.deepEqual(writes, [["/q/requirements/r/workflow/", { action: "submit", expected_version: 4, comment: "" }]]);
});
test("需求保持原状态不发送写入，验收走原验收接口保留说明", async () => {
  const same = load({ next: "draft" });
  await assert.rejects(same.tree.props.onSubmit(new FormData()), /请选择新的需求状态/);
  assert.equal(same.writes.length, 0);
  const accept = load({ status: "approved", next: "completed" });
  const form = new FormData();
  form.set("comment", "已核对文字提示");
  await accept.tree.props.onSubmit(form);
  assert.equal(accept.writes[0][1].action, "accept");
  assert.equal(accept.writes[0][1].comment, "已核对文字提示");
});
