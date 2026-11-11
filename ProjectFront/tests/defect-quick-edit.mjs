import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
function quick(field, value = {}, context = {}) {
  const writes = [],
    exports = {};
  const code = ts.transpileModule(
    readFileSync(new URL("../core/components/quality/defect-quick-edit.tsx", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }
  ).outputText;
  new Function("require", "exports", code)((id) => {
    if (id === "./paged-record-select") return { PagedRecordSelect: () => null };
    if (id === "./api") return { qualityApi: { write: async (...args) => writes.push(args) } };
    if (id === "./types") return { can: () => true, severityNames: { major: "严重", minor: "一般" } };
    if (id === "./shared") return { Modal: () => {}, Field: () => {}, fieldClass: "field" };
    if (id === "react-router") return { Link: () => {} };
    if (id === "@/components/common/project-route-link") return { ProjectRouteLink: () => {} };
    return require(id);
  }, exports);
  const tree = exports.DefectQuickEdit({
    base: "/q/",
    projectUrl: "/p/",
    field,
    value: { id: "d", title: "问题", status: "open", severity: "major", edit_version: 4, ...value },
    context: {
      is_manager: true,
      user_id: "manager",
      business_roles_enabled: true,
      members: [{ id: "tech", name: "技术员", business_role: "TECHNICIAN" }],
      ...context,
    },
    onSaved: async () => {},
    onClose() {},
  });
  return { tree, writes };
}
test("列表调整严重程度只提交该字段与并发版本，不影响状态及负责人", async () => {
  const { tree, writes } = quick("severity", { assignee_id: "manager" });
  const data = new FormData();
  data.set("severity", "minor");
  await tree.props.onSubmit(data);
  assert.deepEqual(writes[0], ["/q/defects/d/", { severity: "minor", expected_version: 4 }, "patch"]);
});
test("首次指派只提交负责人；已有负责人走交接协议", async () => {
  await Promise.all(
    [null, "old"].map(async (assignee_id) => {
      const { tree, writes } = quick("assignee", { assignee_id });
      const data = new FormData();
      data.set("assignee_id", "tech");
      data.set("reason", "分工调整");
      await tree.props.onSubmit(data);
      if (assignee_id)
        assert.deepEqual(writes[0], [
          "/q/defects/d/team/",
          { action: "transfer", user_id: "tech", reason: "分工调整", expected_version: 4 },
        ]);
      else assert.deepEqual(writes[0], ["/q/defects/d/", { assignee_id: "tech", expected_version: 4 }, "patch"]);
    })
  );
});
test("已关闭、归档、待交接、无技术员及非经理不提供错误提交入口", () => {
  for (const [value, context] of [
    [{ status: "closed" }, {}],
    [{ archived_at: "2026-11-07" }, {}],
    [{ pending_assignee_id: "tech" }, {}],
    [{}, { members: [] }],
    [{}, { is_manager: false }],
  ])
    assert.equal(quick("assignee", value, context).tree.props.onSubmit, undefined);
});
