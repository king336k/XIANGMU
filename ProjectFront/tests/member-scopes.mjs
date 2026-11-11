import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
function load() {
  const exports = {};
  new Function(
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/settings/member-scope-data.ts", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }
    ).outputText
  )(exports);
  return exports;
}
function walk(node) {
  if (!node || typeof node !== "object") return [];
  if (Array.isArray(node)) return node.flatMap(walk);
  return [node, ...walk(node.props?.children)];
}

const Scope = () => null;
const workspace = { kind: "workspace", id: "w", name: "空间", access_role: 15, roles: [], revision: "revision-w" };
const project = {
  kind: "project",
  id: "p",
  workspace_id: "w",
  name: "项目A",
  access_role: 15,
  roles: ["PROJECT_MANAGER"],
  revision: "revision-p",
};
test("分页或搜索切换后仍只提交显式更改的范围，不替换所有访问", () => {
  const api = load();
  let pending = api.updateScopeChanges({}, project, 15, ["REGRESSION_TESTER"]);
  pending = api.updateScopeChanges(pending, { ...project, id: "p2", revision: "r2" }, 15, [
    "TECHNICIAN",
    "REGRESSION_TESTER",
  ]);
  assert.deepEqual(
    Object.values(pending).map((row) => [row.id, row.roles]),
    [
      ["p", ["REGRESSION_TESTER"]],
      ["p2", ["TECHNICIAN", "REGRESSION_TESTER"]],
    ]
  );
  assert.equal(pending["project:p"].expected_revision, "revision-p");
  assert.equal(api.buildScopePayload(pending).changes.length, 2);
});
test("仅加入空间不自动选项目；取消空间清掉其待新增项目但保留其他空间修改", () => {
  const api = load();
  const first = api.updateScopeChanges({}, { ...workspace, access_role: 0 }, 15);
  assert.deepEqual(
    api.buildScopePayload(first).changes.map((row) => row.kind),
    ["workspace"]
  );
  let pending = api.updateScopeChanges({}, { ...project, access_role: 0 }, 15, ["TECHNICIAN"]);
  pending = api.updateScopeChanges(pending, { ...project, id: "q", workspace_id: "other" }, 15, ["REGRESSION_TESTER"]);
  pending = api.updateScopeChanges(pending, workspace, 0);
  assert.equal(pending["project:p"], undefined);
  assert.ok(pending["project:q"]);
  assert.ok(pending["workspace:w"]);
});
test("恢复原选择不产生写操作，项目角色按集合比较且同一范围保持初始revision", () => {
  const api = load();
  let pending = api.updateScopeChanges({}, project, 15, ["REGRESSION_TESTER"]);
  pending = api.updateScopeChanges(pending, project, 15, ["PROJECT_MANAGER"]);
  assert.deepEqual(api.buildScopePayload(pending).changes, []);
  const old = { ...project, roles: ["TECHNICIAN", "REGRESSION_TESTER"] };
  assert.deepEqual(api.updateScopeChanges({}, old, 15, ["REGRESSION_TESTER", "TECHNICIAN"]), {});
});

test("服务器保存成功而列表刷新失败时明确显示已保存，不误报整个权限操作失败", async () => {
  const exp = {},
    messages = [];
  let index = 0;
  const pending = { "workspace:w": { kind: "workspace", id: "w", access_role: 15, expected_revision: "r" } };
  const React = require("react");
  const mocks = {
    react: {
      ...React,
      useState(initial) {
        const i = index++;
        return [
          i === 2 ? pending : initial,
          (value) => {
            if (i === 4) messages.push(value);
          },
        ];
      },
    },
    swr: {
      default: () => ({ data: { results: [], count: 0, is_administrator: false } }),
      useSWRConfig: () => ({
        mutate: async () => {
          throw Error("读取失败");
        },
      }),
    },
    "@plane/ui": { Button: "Button" },
    "@/components/quality/api": {
      qualityApi: { write: async () => ({ saved: 1 }) },
      errorMessage: (error) => error.message,
    },
    "@/components/quality/shared": { Paging: "Paging", fieldClass: "field" },
    "./member-management-data": { ACCESS_LABELS: {}, DUTY_LABELS: {} },
    "./member-scope-data": { buildScopePayload: () => ({ changes: Object.values(pending) }) },
  };
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/settings/member-scope-access.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }
    ).outputText
  )((id) => mocks[id] || require(id), exp);
  const tree = exp.MemberScopeAccess({ userId: "u", own: false, onSaved: async () => {} });
  await walk(tree)
    .find((node) => node.type === "Button")
    .props.onClick();
  assert.ok(messages.at(-1).includes("已保存"), messages.at(-1));
  assert.ok(messages.at(-1).includes("刷新失败"), messages.at(-1));
});

test("管理员打开人员编辑即看到统一工作空间与项目选择，不保留第二套当前项目岗位表", () => {
  const exports = {},
    React = require("react");
  const mocks = {
    react: { ...React, useState: (value) => [value, () => {}] },
    "@plane/ui": { Button: "Button" },
    "@/components/quality/shared": { Modal: "Modal", Field: "Field" },
    "@/components/quality/api": { qualityApi: {}, errorMessage: () => "" },
    "./member-management-data": { ACCESS_LABELS: {}, DUTY_LABELS: {} },
    "./member-scope-access": { MemberScopeAccess: Scope },
  };
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/settings/member-permissions-modal.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }
    ).outputText
  )((id) => mocks[id] || require(id), exports);
  const tree = exports.MemberPermissionsModal({
    person: { id: "u", username: "test", roles: [] },
    canAdmin: true,
    currentUserId: "admin",
    onSaved: async () => {},
    onClose() {},
  });
  assert.equal(walk(tree).filter((node) => node.type === Scope).length, 1);
  assert.ok(!walk(tree).some((node) => node.props?.children === "业务岗位"));
  assert.ok(walk(tree).some((node) => node.props?.children === "工作空间与项目"));
});
