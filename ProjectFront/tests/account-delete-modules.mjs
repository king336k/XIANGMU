import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
function load(file, mocks = {}) {
  const e = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL("../core/components/" + file, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
    }).outputText
  )(
    (id) =>
      mocks[id] ??
      (["react", "react/jsx-runtime"].includes(id) ? require(id) : new Proxy({}, { get: () => () => null })),
    e
  );
  return e;
}
const nodes = (t) =>
  !t || typeof t !== "object" ? [] : Array.isArray(t) ? t.flatMap(nodes) : [t, ...nodes(t.props?.children)];
const data = load("settings/member-management-data.ts");
test("module responsibility applies only to technicians while administrators retain all access", () => {
  assert.equal(data.accountModuleLabel({ is_administrator: true, business_roles: ["TECHNICIAN"] }), "所有权限");
  for (const roles of [[], ["REGRESSION_TESTER"], ["PROJECT_MANAGER"]])
    assert.equal(data.accountModuleLabel({ business_roles: roles }), "暂不设置");
  assert.equal(data.accountModuleLabel({ business_roles: ["TECHNICIAN", "REGRESSION_TESTER"] }), "未设置");
  assert.equal(data.canSetAccountModules({ is_administrator: true, business_roles: ["TECHNICIAN"] }), false);
  assert.equal(data.canSetAccountModules({ business_roles: ["TECHNICIAN"] }), true);
});
const Modal = () => null;
function harness(canAdmin = true) {
  let rows = [
    { id: "self", username: "当前管理员", is_administrator: true, business_roles: [] },
    { id: "tester", username: "测试员", business_roles: ["REGRESSION_TESTER"] },
    { id: "tech", username: "技术员", business_roles: ["TECHNICIAN"] },
  ];
  let index = 0,
    fail = false;
  const state = [],
    writes = [];
  const { ManagedAccounts } = load("settings/managed-accounts.tsx", {
    react: {
      ...React,
      useState: (value) => {
        const at = index++;
        if (!(at in state)) state[at] = value;
        return [state[at], (next) => (state[at] = next)];
      },
    },
    swr: {
      default: () => ({ data: { results: rows, count: rows.length } }),
      useSWRConfig: () => ({ mutate: async () => {} }),
    },
    "./member-management-data": data,
    "@/components/quality/shared": { Modal, Paging: () => null, fieldClass: "" },
    "@/components/quality/api": {
      qualityApi: {
        write: async (...args) => {
          writes.push(args);
          if (fail) throw Error("账号仍有未完成事项");
        },
      },
      errorMessage: (error) => error.message,
    },
  });
  return {
    writes,
    Modal,
    refreshPerson(id, changes) {
      rows = rows.map((person) => (person.id === id ? Object.assign({}, person, changes) : person));
    },
    fail() {
      fail = true;
    },
    render() {
      index = 0;
      return ManagedAccounts({
        workspace: "w",
        projectId: "p",
        currentUserId: "self",
        view: "accounts",
        canAdmin,
        onViewChange() {},
      });
    },
  };
}
test("account row module labels match role and only technicians receive module configuration entry", () => {
  const h = harness(),
    tree = h.render(),
    rows = nodes(tree).filter((n) => n.type === "tr" && n.props.children?.some?.((c) => c.type === "td"));
  assert.ok(nodes(rows[0]).some((n) => n.props?.children === "所有权限"));
  assert.ok(nodes(rows[1]).some((n) => n.props?.children === "暂不设置"));
  assert.equal(nodes(rows[0]).filter((n) => n.type === "button" && n.props.children === "模块负责人").length, 0);
  assert.equal(nodes(rows[1]).filter((n) => n.type === "button" && n.props.children === "模块负责人").length, 0);
  assert.equal(nodes(rows[2]).filter((n) => n.type === "button" && n.props.children === "模块负责人").length, 1);
});
test("administrator deletion is confirmed in-place, excludes self and preserves dialog on a server conflict", async () => {
  const h = harness();
  let tree = h.render();
  const remove = nodes(tree).filter((n) => n.type === "button" && n.props.children === "删除账号");
  assert.equal(remove.length, 2);
  assert.equal(h.writes.length, 0);
  remove[0].props.onClick();
  tree = h.render();
  const modal = nodes(tree).find((n) => n.type === h.Modal && n.props.submitLabel === "删除账号");
  assert.ok(modal);
  assert.ok(nodes(modal).some((n) => n.props?.children === "删除后无法登录，历史记录保留。"));
  h.fail();
  await assert.rejects(modal.props.onSubmit(), /未完成事项/);
  assert.deepEqual(h.writes[0], ["/api/quality-auth/accounts/", { user_id: "tester" }, "delete"]);
  assert.ok(nodes(h.render()).some((n) => n.type === h.Modal && n.props.submitLabel === "删除账号"));
  assert.equal(
    nodes(harness(false).render()).filter((n) => n.type === "button" && n.props.children === "删除账号").length,
    0
  );
});
test("delete transport sends the account id in the DELETE body", async () => {
  const calls = [];
  const { qualityApi } = load("quality/api.ts", {
    "@/services/api.service": {
      APIService: class {
        async delete(...args) {
          calls.push(args);
          return { data: {} };
        }
      },
    },
    "@plane/constants": { API_BASE_URL: "" },
  });
  await qualityApi.write("/api/quality-auth/accounts/", { user_id: "person" }, "delete");
  assert.deepEqual(calls, [["/api/quality-auth/accounts/", { user_id: "person" }]]);
});

test("fresh account data restores the module button after tester becomes technician, including multi-duty, but never administrator", () => {
  const h = harness();
  const row = (tree, username) =>
    nodes(tree).find(
      (n) => n.type === "tr" && nodes(n).some((child) => child.type === "p" && child.props.children === username)
    );
  const buttons = (item) => nodes(item).filter((n) => n.type === "button" && n.props.children === "模块负责人");
  let tree = h.render();
  assert.equal(buttons(row(tree, "测试员")).length, 0);
  assert.ok(nodes(row(tree, "测试员")).some((n) => n.props?.children === "暂不设置"));
  h.refreshPerson("tester", { business_roles: ["TECHNICIAN"] });
  tree = h.render();
  assert.equal(buttons(row(tree, "测试员")).length, 1);
  assert.ok(nodes(row(tree, "测试员")).some((n) => n.props?.children === "未设置"));
  h.refreshPerson("tester", { business_roles: ["TECHNICIAN", "REGRESSION_TESTER"] });
  tree = h.render();
  assert.equal(buttons(row(tree, "测试员")).length, 1);
  buttons(row(tree, "测试员"))[0].props.onClick();
  assert.ok(nodes(h.render()).some((n) => n.type === h.Modal && n.props.title === "模块责任 · 测试员"));
  h.refreshPerson("tester", { is_administrator: true });
  tree = h.render();
  assert.equal(buttons(row(tree, "测试员")).length, 0);
  assert.ok(nodes(row(tree, "测试员")).some((n) => n.props?.children === "所有权限"));
  h.refreshPerson("tester", { is_administrator: false, business_roles: ["REGRESSION_TESTER"] });
  tree = h.render();
  assert.equal(buttons(row(tree, "测试员")).length, 0);
});
