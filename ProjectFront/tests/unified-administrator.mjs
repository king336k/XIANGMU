import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
const stubs = new Map();
const stub = (k) => {
  if (!stubs.has(k)) stubs.set(k, () => null);
  return stubs.get(k);
};
function harness(file, data, context = {}, extraProps = {}) {
  const state = [],
    writes = [];
  let cursor = 0;
  const exp = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(`../core/components/quality/${file}.tsx`, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((id) => {
    if (id === "react")
      return {
        ...React,
        useState(initial) {
          const at = cursor++;
          if (!(at in state)) state[at] = initial;
          return [
            state[at],
            (v) => {
              state[at] = v;
            },
          ];
        },
      };
    if (id === "react/jsx-runtime" || id === "uuid") return require(id);
    if (id === "swr") return { default: () => ({ data, mutate: async () => {} }) };
    if (id === "./connection-form-data") {
      const helper = {};
      new Function(
        "exports",
        ts.transpileModule(
          readFileSync(new URL("../core/components/quality/connection-form-data.ts", import.meta.url), "utf8"),
          { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }
        ).outputText
      )(helper);
      return helper;
    }
    if (id === "./api") return { qualityApi: { write: async (...args) => writes.push(args) }, errorMessage: String };
    if (id === "./use-collection-pagination")
      return { useCollectionPagination: () => ({ query: "page=1", paging: {} }) };
    if (id === "@/hooks/use-resolved-project-params")
      return { useResolvedProjectParams: () => ({ workspaceSlug: "w", projectId: "p" }) };
    return new Proxy({}, { get: (_, k) => (k === "fieldClass" ? "field" : stub(k)) });
  }, exp);
  return {
    writes,
    render() {
      cursor = 0;
      return exp[
        file === "account-manager"
          ? "AccountManager"
          : file === "connection-settings"
            ? "ConnectionSettings"
            : "BusinessRolePanel"
      ]({
        base: "/q/",
        context,
        members: [],
        project: { workspace: "w", id: "p" },
        onSaved: async () => {},
        ...extraProps,
      });
    },
  };
}
const nodes = (t) =>
  !t || typeof t !== "object" ? [] : Array.isArray(t) ? t.flatMap(nodes) : [t, ...nodes(t.props?.children)];
const text = (t) =>
  nodes(t)
    .flatMap((n) => [n.props?.children].flat())
    .filter((v) => typeof v === "string")
    .join("");
const button = (t, label) => nodes(t).find((n) => n.type === stub("Button") && n.props.children === label);
const roledata = {
  enabled: true,
  roles: {
    PLATFORM_ADMIN: "管理员",
    PROJECT_MANAGER: "项目经理",
    TECHNICIAN: "技术员",
    REGRESSION_TESTER: "测试员",
    REPORTER: "数采员",
  },
  results: [
    { user_id: "admin", name: "真正管理员", role: "PLATFORM_ADMIN", roles: ["PLATFORM_ADMIN"], is_administrator: true },
  ],
};
test("项目岗位选择永不授予管理员，旧岗位字符串不会冒充全局管理员权限", () => {
  const h = harness("business-role-panel", roledata, {
    members: [],
    business_role: "PLATFORM_ADMIN",
    business_roles: ["PLATFORM_ADMIN"],
    is_administrator: false,
  });
  let tree = h.render();
  assert.equal(button(tree, "调整权限策略"), undefined);
  assert.match(text(tree), /管理员/);
  assert.doesNotMatch(text(tree), /平台管理员|实例管理员|项目管理员/);
  button(tree, "设置成员角色").props.onClick();
  tree = h.render();
  assert.equal(
    nodes(tree).some((n) => n.type === "input" && n.props.name === "roles" && n.props.value === "PLATFORM_ADMIN"),
    false
  );
});
test("只有后端明确canonical旗标才显示管理员策略操作", () => {
  const h = harness("business-role-panel", roledata, { members: [], is_administrator: true });
  assert.ok(button(h.render(), "调整权限策略"));
});
test("账号目录没有can_manage_administrators时无授予入口，项目岗位不提供管理员", () => {
  const h = harness("account-manager", {
    can_manage: true,
    can_manage_administrators: false,
    count: 1,
    results: [{ id: "u", username: "tester", source: "本平台" }],
  });
  let tree = h.render();
  assert.equal(button(tree, "设为管理员"), undefined);
  button(tree, "加入本项目").props.onClick();
  tree = h.render();
  assert.equal(
    nodes(tree).some((n) => n.type === "option" && n.props.value === "PLATFORM_ADMIN"),
    false
  );
});
test("管理员授权须确认后用专用PATCH布尔契约，创建项目岗位不混入授权", async () => {
  const h = harness("account-manager", {
    can_manage: true,
    can_manage_administrators: true,
    count: 1,
    results: [{ id: "u", username: "tester", source: "本平台", is_administrator: false }],
  });
  let tree = h.render();
  button(tree, "设为管理员").props.onClick();
  assert.equal(h.writes.length, 0);
  tree = h.render();
  let modal = nodes(tree).find((n) => n.type === stub("Modal"));
  assert.equal(modal.props.title, "设置管理员");
  await modal.props.onSubmit();
  assert.deepEqual(h.writes, [["/api/quality-auth/accounts/", { user_id: "u", administrator: true }, "patch"]]);
});

const initialRoleMap = {
  Admin: "PLATFORM_ADMIN",
  Manager: "PROJECT_MANAGER",
  TeamLeader: "REPORTER",
  Annotator: "REPORTER",
  Auditor: "REPORTER",
  Collector: "REPORTER",
};
function assertServerManagedRolePolicy(tree) {
  assert.equal(
    nodes(tree).some(
      (n) =>
        ["select", "input"].includes(n.type) &&
        (n.props.name?.startsWith("login_role_") || n.props["aria-label"]?.endsWith("首次登录岗位"))
    ),
    false
  );
}
test("首次来源岗位由服务端固定策略处理，不再要求填写角色对应表", () => {
  const h = harness("connection-settings", { can_configure: true, results: [] });
  button(h.render(), "添加连接").props.onClick();
  assertServerManagedRolePolicy(h.render());
});
test("旧TECH配置不会成为可编辑岗位，表单篡改不发送且空凭据沿用后端值", async () => {
  const h = harness("connection-settings", {
    can_configure: true,
    results: [
      {
        source_instance: "source-old",
        kind: "data_platform",
        base_url: "https://source.example.invalid",
        token_present: true,
        login_role_map: Object.fromEntries(Object.keys(initialRoleMap).map((key) => [key, "TECHNICIAN"])),
      },
    ],
  });
  button(h.render(), "编辑连接").props.onClick();
  const tree = h.render();
  assertServerManagedRolePolicy(tree);
  const form = new FormData();
  form.set("source_instance", "source-old");
  form.set("kind", "data_platform");
  form.set("base_url", "https://source.example.invalid");
  for (const source of Object.keys(initialRoleMap)) form.set(`login_role_${source}`, "TECHNICIAN");
  await nodes(tree)
    .find((n) => n.type === stub("Modal"))
    .props.onSubmit(form);
  assert.equal("login_role_map" in h.writes[0][1], false);
  assert.equal("service_token" in h.writes[0][1], false);
  assert.equal("bridge_secret" in h.writes[0][1], false);
  assert.equal("clear_token" in h.writes[0][1], false);
});

test("项目设置保留账号加入项目，但全局创建与授权只在账号与权限入口显示", () => {
  const data = {
    can_manage: true,
    can_manage_administrators: true,
    count: 1,
    results: [{ id: "u", username: "worker", source: "本平台" }],
  };
  const tree = harness("account-manager", data, {}, { projectOnly: true }).render();
  assert.ok(button(tree, "加入本项目"));
  assert.equal(button(tree, "创建项目平台账号"), undefined);
  assert.equal(button(tree, "设为管理员"), undefined);
  const denied = harness(
    "account-manager",
    { ...data, can_manage_administrators: false },
    {},
    { administratorsOnly: true }
  ).render();
  assert.equal(button(denied, "创建项目平台账号"), undefined);
  assert.match(text(denied), /没有账号管理权限/);
});
test("项目角色面板可不重复嵌套全局账号管理，默认调用兼容", () => {
  const tree = harness("business-role-panel", roledata, { members: [] }, { includeAccounts: false }).render();
  assert.equal(
    nodes(tree).some((n) => n.type === stub("AccountManager")),
    false
  );
  assert.equal(
    nodes(harness("business-role-panel", roledata, { members: [] }).render()).some(
      (n) => n.type === stub("AccountManager")
    ),
    true
  );
});

test("项目岗位移除独立REPORTER，普通成员加入时不自动授予专职岗位", async () => {
  const roles = harness("business-role-panel", roledata, { members: [] });
  button(roles.render(), "设置成员角色").props.onClick();
  assert.ok(!nodes(roles.render()).some((n) => n.type === "input" && n.props.value === "REPORTER"));
  const accounts = harness("account-manager", {
    can_manage: true,
    count: 1,
    results: [{ id: "u", username: "user", source: "本平台" }],
  });
  button(accounts.render(), "加入本项目").props.onClick();
  const tree = accounts.render();
  const select = nodes(tree).find((n) => n.type === "select" && n.props.name === "role");
  assert.equal(nodes(select).find((n) => n.type === "option").props.value, "");
  assert.ok(!nodes(select).some((n) => n.props?.value === "REPORTER"));
  const modal = nodes(tree).find((n) => n.type === stub("Modal") && n.props.title === "加入项目并分配岗位");
  await modal.props.onSubmit(new Map([["role", ""]]));
  assert.deepEqual(accounts.writes[0][1], { user_id: "u" });
});
