import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const source = readFileSync(new URL("../core/components/quality/defect-form.tsx", import.meta.url), "utf8");
function form(mode, onWrite, original = {}) {
  let calls = 0;
  const exports = {};
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  new Function("require", "exports", code)((id) => {
    if (id === "react")
      return {
        ...React,
        useState: (value) => [calls++ === 1 ? mode : value, () => {}],
        useRef: (value) => ({ current: value }),
      };
    if (id === "swr") return { default: () => ({ data: [] }) };
    if (id === "./api")
      return {
        qualityApi: {
          write: async (...args) => {
            onWrite(...args);
            return { id: "record" };
          },
        },
      };
    if (id === "./types")
      return {
        can: () => true,
        statusNames: { open: "待处理", in_progress: "处理中" },
        severityNames: { major: "严重" },
      };
    if (id === "./defect-attachments") return { uploadDefectFiles: async () => {} };
    if (id === "@plane/utils") return {};
    if (id.startsWith("./")) return new Proxy({}, { get: (_, key) => (key === "fieldClass" ? "field" : () => null) });
    if (id === "react-router") return { Link: () => null };
    if (id === "@/components/common/project-route-link") return { ProjectRouteLink: () => null };
    return require(id);
  }, exports);
  return exports.DefectForm({
    base: "/quality/",
    context: { is_manager: true, issues: [], members: [] },
    value: {
      id: "record",
      title: "Original",
      description: "Original description",
      status: "open",
      edit_version: 3,
      events: [],
      ...original,
    },
    onClose() {},
    onSaved: async () => {},
    projectUrl: "/project",
  });
}
test("编辑基本信息不携带状态、负责人、修复信息", async () => {
  let payload;
  const tree = form("details", (_, data) => {
    payload = data;
  });
  const values = new FormData();
  for (const [key, value] of Object.entries({
    title: "New title",
    description: "New description",
    severity: "major",
    affected_build: "v1",
  }))
    values.set(key, value);
  await tree.props.onSubmit(values);
  assert.equal(tree.props.title, "编辑缺陷");
  assert.equal(payload.title, "New title");
  for (const key of ["status", "assignee_id", "resolution", "repair_issue_id"]) assert.ok(!(key in payload), key);
  assert.equal(payload.expected_version, 3);
});
test("处理流程不携带标题、现象和严重程度", async () => {
  let payload;
  const tree = form("workflow", (_, data) => {
    payload = data;
  });
  const values = new FormData();
  values.set("resolution", "investigating");
  await tree.props.onSubmit(values);
  assert.equal(tree.props.title, "更新处理状态");
  assert.equal(payload.resolution, "investigating");
  for (const key of ["title", "description", "severity", "affected_build"]) assert.ok(!(key in payload), key);
});

test("更新状态不重复指派原负责人，兼容启用业务角色前的记录", async () => {
  let payload;
  const tree = form(
    "workflow",
    (_, data) => {
      payload = data;
    },
    { assignee_id: "existing-manager" }
  );
  await tree.props.onSubmit(new FormData());
  assert.ok(!("assignee_id" in payload));
  assert.equal(payload.status, "open");
});

test("编辑缺陷可填写修复版本和首次指派，并保留状态不变", async () => {
  let payload;
  const tree = form("details", (_, data) => {
    payload = data;
  });
  const values = new FormData();
  values.set("title", "问题");
  values.set("fixed_build", "v2");
  values.set("assignee_id", "tech");
  await tree.props.onSubmit(values);
  assert.equal(payload.fixed_build, "v2");
  assert.equal(payload.assignee_id, "tech");
  assert.ok(!("status" in payload));
});
