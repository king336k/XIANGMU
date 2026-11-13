import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const load = (file, mocks) => {
  const exports = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(`../core/components/settings/${file}`, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((id) => {
    if (mocks[id]) return mocks[id];
    if (id === "./module-owner-fields") return { ModuleOwnerFields: "ModuleOwnerFields" };
    if (id === "./module-owner-data") return load("module-owner-data.ts", {});
    return require(id);
  }, exports);
  return exports;
};
const walk = (node) =>
  !node || typeof node !== "object"
    ? []
    : Array.isArray(node)
      ? node.flatMap(walk)
      : [node, ...walk(node.props?.children)];
const common = {
  react: { ...React, useState: (value) => [value, () => {}], useRef: () => ({ current: {} }) },
  swr: {
    default: () => ({ data: { results: [], count: 0 }, mutate: async () => {} }),
    useSWRConfig: () => ({ mutate: async () => {} }),
  },
  "@plane/ui": { Button: "Button" },
  "@/components/quality/shared": { Modal: "Modal", Field: "Field", Paging: "Paging", fieldClass: "field" },
  "@/components/quality/api": { qualityApi: {}, errorMessage: (error) => error.message },
  "./member-scope-access": { MemberScopeAccess: "MemberScopeAccess" },
  "./member-management-data": { DUTY_LABELS: { TECHNICIAN: "技术员" }, ACCESS_LABELS: { 15: "可参与项目" } },
};
test("添加成员只选择已有普通账号，不混入创建账号或空项目加入路径", () => {
  const api = load("add-managed-member.tsx", common);
  const tree = api.AddManagedMember({
    workspace: "w",
    projectId: "p",
    canAdmin: true,
    onSaved: async () => {},
    onClose() {},
  });
  assert.ok(!walk(tree).some((n) => n.props?.children === "创建账号"));
  assert.ok(!walk(tree).some((n) => n.type === "input" && n.props.name === "password"));
});
test("工作空间授权仅展示工作空间选择，不展示项目选择", () => {
  const api = load("member-scope-access.tsx", {
    ...common,
    "./member-scope-data": { buildScopePayload: () => ({ changes: [] }) },
  });
  const tree = api.ScopeChoices({ endpoint: "/scopes/", mode: "workspace", pending: {}, onChange() {} });
  assert.ok(walk(tree).some((n) => n.props?.["aria-label"] === "搜索工作空间"));
  assert.ok(!walk(tree).some((n) => n.props?.children === "选择项目"));
});

test("创建账号默认不授权，授权入口只提供互斥的工作空间或项目模式", () => {
  const api = load("create-managed-account.tsx", {
    ...common,
    "./member-scope-access": { ScopeChoices: "ScopeChoices" },
    "./member-scope-data": { updateScopeChanges() {} },
  });
  const tree = api.CreateManagedAccount({ onSaved: async () => {}, onClose() {} });
  const radios = walk(tree).filter((node) => node.type === "input" && node.props.name === "grant_mode");
  assert.deepEqual(
    radios.map((node) => [node.props.value, node.props.checked]),
    [
      ["none", true],
      ["workspace", false],
      ["project", false],
    ]
  );
  assert.ok(!walk(tree).some((node) => node.type === "ScopeChoices"));
});

test("编辑范围的继承项目不可移除，仍可单独增加项目岗位", () => {
  const api = load("member-scope-access.tsx", {
    ...common,
    swr: {
      default: () => ({
        data: {
          results: [
            {
              kind: "project",
              id: "p",
              name: "项目",
              workspace_name: "空间",
              access_role: 15,
              roles: [],
              inherited_access: true,
              inherited_roles: ["TECHNICIAN"],
            },
          ],
          count: 1,
        },
      }),
    },
    "./member-scope-data": { scopeKey: () => "project:p" },
  });
  const tree = api.ScopeChoices({ endpoint: "/scopes/", mode: "project", pending: {}, onChange() {} });
  assert.equal(walk(tree).find((node) => node.props?.["aria-label"] === "项目访问").props.disabled, true);
  assert.ok(walk(tree).some((node) => node.type === "input" && node.props.type === "checkbox" && !node.props.disabled));
});

test("账号POST成功后刷新失败，再次提交只刷新且不重复POST", async () => {
  const states = [],
    refs = [];
  let index = 0,
    refIndex = 0,
    posts = 0,
    refreshes = 0;
  const api = load("create-managed-account.tsx", {
    ...common,
    react: {
      ...React,
      useState(initial) {
        const i = index++;
        if (!(i in states)) states[i] = initial;
        return [
          states[i],
          (value) => {
            states[i] = value;
          },
        ];
      },
      useRef(initial) {
        const i = refIndex++;
        return (refs[i] ||= { current: initial });
      },
    },
    "@/components/quality/api": {
      qualityApi: {
        write: async () => {
          posts++;
          return { id: "u" };
        },
      },
    },
    "./member-scope-access": { ScopeChoices: "ScopeChoices" },
    "./member-scope-data": {},
  });
  const render = () => {
    index = 0;
    refIndex = 0;
    return api.CreateManagedAccount({
      onSaved: async () => {
        if (++refreshes === 1) throw Error("refresh offline");
      },
      onClose() {},
    });
  };
  let tree = render();
  const form = new FormData();
  form.set("username", "single-account");
  form.set("password", "test-password");
  await assert.rejects(tree.props.onSubmit(form), /账号已创建.*刷新失败/);
  tree = render();
  assert.equal(tree.props.submitLabel, "重试刷新");
  assert.ok(!walk(tree).some((node) => node.type === "input" && node.props.name === "password"));
  await tree.props.onSubmit(form);
  assert.equal(posts, 1);
  assert.equal(refreshes, 2);
});
