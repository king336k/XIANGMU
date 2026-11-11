import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const helper = {};
function loadHelper() {
  new Function(
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/settings/management-paths.ts", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS } }
    ).outputText
  )(helper);
}
test("旧业务设置链接迁移保留项目和其他查询条件", () => {
  loadHelper();
  assert.equal(
    helper.movedSettingsPath("w", "CODE", "uuid", "roles", new URLSearchParams("tab=roles&version=v2&page=3")),
    "/w/settings/members/?version=v2&page=3&project=uuid"
  );
  assert.equal(
    helper.movedSettingsPath("w", "CODE", "uuid", "integrations", new URLSearchParams("tab=integrations&version=v2")),
    "/w/settings/sources/?version=v2&project=uuid"
  );
  assert.equal(
    helper.movedSettingsPath("w", "CODE", "uuid", "settings", new URLSearchParams("tab=settings&version=v2")),
    "/w/settings/models/?version=v2&project=uuid"
  );
  assert.equal(
    helper.movedSettingsPath("w", "CODE", "uuid", "releases", new URLSearchParams("tab=releases&version=v2")),
    "/w/p/CODE/versions/?version=v2&tab=acceptance"
  );
  assert.equal(helper.movedSettingsPath("w", "CODE", "uuid", "cases", new URLSearchParams()), undefined);
});
const nodes = (t) =>
  !t || typeof t !== "object" ? [] : Array.isArray(t) ? t.flatMap(nodes) : [t, ...nodes(t.props?.children)];
const stubs = new Map();
const stub = (n) => {
  if (!stubs.has(n)) stubs.set(n, () => null);
  return stubs.get(n);
};
function management(context, section = "connections", query = "project=p") {
  const exp = {},
    requests = [];
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/settings/platform-management.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
    ).outputText
  )((id) => {
    if (id === "react/jsx-runtime") return require(id);
    if (id === "mobx-react") return { observer: (x) => x };
    if (id === "react-router")
      return { useLocation: () => ({ hash: "" }), useSearchParams: () => [new URLSearchParams(query), () => {}] };
    if (id === "next/navigation") return { useParams: () => ({ workspaceSlug: "w" }) };
    if (id === "@/hooks/store/use-project")
      return {
        useProject: () => ({
          joinedProjectIds: ["p", "q"],
          getPartialProjectById: (projectKey) => ({ id: projectKey, name: projectKey }),
        }),
      };
    if (id === "swr")
      return {
        default: (key) => {
          requests.push(key);
          return { data: context, mutate: async () => {} };
        },
      };
    return new Proxy({}, { get: (_, key) => stub(key) });
  }, exp);
  return { tree: exp.PlatformManagement({ section }), requests };
}
test("平台连接使用独立全局权限接口无需项目，模型仍按项目能力核验", () => {
  const ordinary = { is_manager: true, is_administrator: false, can_configure_model: false };
  for (const context of [undefined, ordinary, { ...ordinary, is_administrator: true }]) {
    for (const query of ["", "project=p", "project=other"]) {
      const page = management(context, "connections", query);
      const connection = nodes(page.tree).filter((node) => node.type === stub("ConnectionSettings"));
      assert.equal(connection.length, 1);
      assert.equal(connection[0].props.endpoint, "/api/quality-auth/connections/");
      assert.equal(connection[0].props.base, undefined);
      assert.deepEqual(page.requests, [null]);
      assert.ok(!nodes(page.tree).some((node) => node.type === "select" && node.props["aria-label"] === "选择项目"));
    }
  }
  // The global child fetches can_configure from its administrator-only endpoint;
  // a project context must neither grant nor deny global authority.
  assert.equal(
    nodes(management(ordinary, "models").tree).some((n) => n.type === stub("ModelSettings")),
    false
  );
  assert.ok(
    nodes(management({ ...ordinary, can_configure_model: true }, "models").tree).some(
      (n) => n.type === stub("ModelSettings") && n.props.base.endsWith("/knowledge/")
    )
  );
  assert.equal(
    nodes(management({ ...ordinary, can_configure_model: true }, "models", "project=other").tree).some(
      (n) => n.type === stub("ModelSettings")
    ),
    false
  );
  assert.deepEqual(management(ordinary, "models", "project=other").requests, [null]);
});

test("设置页有可到达路由，业务工作台仅兼容重定向而不再嵌配置面板", () => {
  const read = (p) => readFileSync(new URL(`../${p}`, import.meta.url), "utf8");
  const routes = read("app/routes/core.ts");
  for (const path of [
    ":workspaceSlug/settings/accounts",
    ":workspaceSlug/settings/connections",
    ":workspaceSlug/settings/models",
    ":workspaceSlug/p/:projectId/settings/sources",
  ])
    assert.ok(routes.includes(path), path);
  const quality = read("core/components/quality/workbench.tsx"),
    knowledge = read("core/components/knowledge/workbench.tsx");
  assert.doesNotMatch(quality, /<BusinessRolePanel|<IntegrationsPanel/);
  assert.doesNotMatch(knowledge, /<ModelSettings/);
  assert.match(quality, /movedSettingsPath/);
  assert.match(knowledge, /movedSettingsPath/);
  assert.match(
    read("app/(all)/[workspaceSlug]/(settings)/settings/projects/[projectId]/members/page.tsx"),
    /SettingsRedirect/
  );
});

test("项目任务与需求菜单分开且保留内部键", () => {
  const read = (p) => readFileSync(new URL(`../${p}`, import.meta.url), "utf8");
  const nav = JSON.parse(read("../packages/i18n/src/locales/zh-CN/navigation.json")).sidebar;
  assert.equal(nav.work_items, "任务");
  assert.equal(nav.cycles, "迭代周期");
  assert.equal(nav.modules, "功能模块");
  assert.equal(nav.views, "任务视图");
  assert.equal(nav.intake, "待评估事项");
  const header = read("core/components/issues/header.tsx");
  assert.match(header, /label="任务"/);
  assert.match(read("core/components/workspace/sidebar/project-navigation.tsx"), /key: "work_items"/);
  assert.match(read("core/components/quality/workbench.tsx"), /name: "执行记录"/);
});

test("旧网址实际渲染replace跳转，权限缺失不会借迁移进入配置", () => {
  const React = require("react");
  const contexts = {
    project_name: "项目",
    identifier: "CODE",
    can_write: true,
    business_roles_enabled: true,
    is_manager: true,
    capabilities: { manage_roles: true },
    can_configure_model: true,
    members: [],
  };
  function render(file, tab, extra = {}) {
    const exp = {};
    new Function(
      "require",
      "exports",
      ts.transpileModule(readFileSync(new URL(`../core/components/${file}/workbench.tsx`, import.meta.url), "utf8"), {
        compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
      }).outputText
    )((id) => {
      if (id === "react")
        return { ...React, useState: (v) => [typeof v === "function" ? v() : v, () => {}], useEffect() {} };
      if (id === "react/jsx-runtime") return require(id);
      if (id === "react-router")
        return {
          Navigate: stub("Navigate"),
          useLocation: () => ({ hash: "" }),
          useSearchParams: () => [new URLSearchParams(`tab=${tab}&version=v2`), () => {}],
          useParams: () => ({ projectId: "CODE" }),
        };
      if (id === "next/navigation" || id === "@/hooks/use-resolved-project-params")
        return {
          useParams: () => ({ workspaceSlug: "w", projectId: "uuid" }),
          useResolvedProjectParams: () => ({ workspaceSlug: "w", projectId: "uuid" }),
        };
      if (id === "swr")
        return {
          default: (key) => ({
            data: key?.includes("context/")
              ? { ...contexts, ...extra }
              : key?.includes("report/")
                ? undefined
                : { results: [] },
            mutate: async () => {},
          }),
          useSWRConfig: () => ({ mutate: async () => {} }),
        };
      if (id === "@/components/settings/management-paths") return helper;
      if (id.endsWith("types"))
        return {
          can: (c, k) => c.capabilities[k] === true,
          canOpenQualityTab: (c) => c?.is_manager === true,
          canOpenKnowledgeTab: (c) => c?.can_configure_model === true,
        };
      if (id === "./pagination") return { normalizedPageParams: (x) => x };
      if (id === "./layout-controls") return { recordLayout: () => "list" };
      if (id === "./api" || id === "@/components/quality/api") return { qualityApi: {}, errorMessage: String };
      return new Proxy({}, { get: (_, key) => stub(key) });
    }, exp);
    return exp[file === "quality" ? "QualityWorkbench" : "KnowledgeWorkbench"]({});
  }
  for (const [module, key, target] of [
    ["quality", "roles", "/w/settings/members/?version=v2&project=uuid"],
    ["quality", "integrations", "/w/settings/sources/?version=v2&project=uuid"],
    ["quality", "releases", "/w/p/CODE/versions/?version=v2&tab=acceptance"],
    ["knowledge", "settings", "/w/settings/models/?version=v2&project=uuid"],
  ]) {
    const view = render(module, key);
    assert.equal(view.type, stub("Navigate"));
    assert.equal(view.props.replace, true);
    assert.equal(view.props.to, target);
  }
  assert.notEqual(render("quality", "roles", { is_manager: false }).type, stub("Navigate"));
  assert.notEqual(render("knowledge", "settings", { can_configure_model: false }).type, stub("Navigate"));
});

test("平台设置切换目录保持项目与版本查询上下文", () => {
  const source = readFileSync(
    new URL("../core/components/settings/workspace/sidebar/item-categories.tsx", import.meta.url),
    "utf8"
  );
  const exp = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } })
      .outputText
  )((id) => {
    if (id === "react/jsx-runtime") return require(id);
    if (id === "mobx-react") return { observer: (x) => x };
    if (id === "react-router")
      return {
        useParams: () => ({ workspaceSlug: "w" }),
        useLocation: () => ({ hash: "" }),
        useSearchParams: () => [new URLSearchParams("project=p&version=v2")],
      };
    if (id === "next/navigation")
      return {
        usePathname: () => "/w/settings/models/",
        useParams: () => ({ workspaceSlug: "w" }),
        useLocation: () => ({ hash: "" }),
        useSearchParams: () => new URLSearchParams("project=p&version=v2"),
      };
    if (id === "swr") return { default: () => ({ data: { can_manage_administrators: true } }) };
    if (id === "@/hooks/store/use-project")
      return { useProject: () => ({ joinedProjectIds: ["p"], getPartialProjectById: () => ({ name: "P" }) }) };
    if (id === "@/components/settings/use-settings-permissions")
      return { useSettingsPermissions: () => ({ allowPermissions: () => true }) };
    if (id === "@plane/i18n") return { useTranslation: () => ({ t: (x) => x }) };
    if (id === "@plane/constants")
      return {
        WORKSPACE_SETTINGS_CATEGORIES: [],
        EUserPermissions: { ADMIN: 20, MEMBER: 15 },
        EUserPermissionsLevel: { PROJECT: "project" },
      };
    return new Proxy({}, { get: (_, key) => stub(key) });
  }, exp);
  const tree = exp.WorkspaceSettingsSidebarItemCategories();
  const hrefs = new Set(
    nodes(tree)
      .filter((n) => n.type === stub("SettingsSidebarItem"))
      .map((n) => n.props.href)
  );
  assert.ok(hrefs.has("/w/settings/connections/?project=p&version=v2"));
  assert.ok(hrefs.has("/w/settings/models/?project=p&version=v2"));
});

test("旧project settings loader保留查询和片段后再交给短链接解析", () => {
  const exp = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../app/routes/redirects/core/project-settings.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS } }
    ).outputText
  )((id) => (id === "react-router" ? { redirect: (target) => ({ target }) } : require(id)), exp);
  let target;
  try {
    exp.clientLoader({
      params: { workspaceSlug: "w", projectId: "p", "*": "members" },
      request: new Request("https://app.invalid/w/projects/p/settings/members/?search=foo&page=3#person"),
    });
  } catch (error) {
    target = error.target;
  }
  assert.equal(target, "/w/settings/projects/p/members/?search=foo&page=3#person");
});

test("浏览器Request去掉片段时旧settings loader仍保留当前URL片段", () => {
  const exp = {};
  new Function(
    "require",
    "exports",
    "window",
    ts.transpileModule(
      readFileSync(new URL("../app/routes/redirects/core/project-settings.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS } }
    ).outputText
  )((id) => (id === "react-router" ? { redirect: (target) => ({ target }) } : require(id)), exp, {
    location: { hash: "#person", pathname: "/w/projects/p/settings/members/", search: "?search=foo" },
  });
  let target;
  try {
    exp.clientLoader({
      params: { workspaceSlug: "w", projectId: "p", "*": "members" },
      request: new Request("https://app.invalid/w/projects/p/settings/members/?search=foo"),
    });
  } catch (error) {
    target = error.target;
  }
  assert.equal(target, "/w/settings/projects/p/members/?search=foo#person");
});
