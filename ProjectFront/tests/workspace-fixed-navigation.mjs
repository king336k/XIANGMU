import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
const items = [
  {
    key: "views",
    href: "/workspace-views/all-issues/",
    labelTranslationKey: "工作总览",
    access: [20, 15, 5],
    highlight: () => false,
  },
  { key: "analytics", href: "/analytics/", labelTranslationKey: "分析", access: [20, 15], highlight: () => false },
  {
    key: "archives",
    href: "/projects/archives/",
    labelTranslationKey: "项目归档",
    access: [20, 15],
    highlight: () => false,
  },
];
function load(path, extra = {}) {
  const api = {};
  const mocks = {
    react: { ...React, useMemo: (fn) => fn(), useEffect() {} },
    "mobx-react": { observer: (fn) => fn },
    "next/navigation": { useParams: () => ({ workspaceSlug: "w" }), usePathname: () => "/w/" },
    "@plane/i18n": { useTranslation: () => ({ t: (x) => x }) },
    "@plane/utils": { joinUrlPath: (a, b) => `/${a}${b}`, cn: () => "" },
    "@plane/constants": {
      EUserPermissionsLevel: { WORKSPACE: "workspace" },
      WORKSPACE_SIDEBAR_DYNAMIC_NAVIGATION_ITEMS_LINKS: items,
      WORKSPACE_SIDEBAR_STATIC_NAVIGATION_ITEMS: {},
      WORKSPACE_SIDEBAR_STATIC_NAVIGATION_ITEMS_LINKS: [],
      WORKSPACE_SIDEBAR_STATIC_PINNED_NAVIGATION_ITEMS_LINKS: [],
    },
    "@/hooks/use-local-storage": { default: () => ({ storedValue: false, setValue() {} }) },
    "@/hooks/store/user": {
      useUser: () => ({ data: { id: "u" } }),
      useUserPermissions: () => ({ allowPermissions: () => true }),
    },
    "@/hooks/store/use-app-theme": { useAppTheme: () => ({ toggleSidebar() {}, toggleExtendedSidebar() {} }) },
    "@/hooks/use-navigation-preferences": {
      usePersonalNavigationPreferences: () => ({ preferences: { items: {} } }),
      useWorkspaceNavigationPreferences: () => ({
        preferences: { items: Object.fromEntries(items.map((i) => [i.key, { is_pinned: false, sort_order: 0 }])) },
        isWorkspaceItemPinned: () => false,
        toggleWorkspaceItem() {},
      }),
    },
    ...extra,
  };
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((id) => mocks[id] || (id === "react/jsx-runtime" ? require(id) : new Proxy({}, { get: () => () => null })), api);
  return api;
}
function walk(node, predicate) {
  if (!node || typeof node !== "object") return [];
  if (Array.isArray(node)) return node.flatMap((n) => walk(n, predicate));
  return [...(predicate(node) ? [node] : []), ...walk(node.props?.children, predicate)];
}
const Item = () => null;
const Denied = () => null;
const RemoteItem = () => null;
const Nav = () => null;

test("旧隐藏/折叠设置不再隐藏三个工作空间入口，移除更多与固定按钮", () => {
  const api = load("../core/components/workspace/sidebar/sidebar-menu-items.tsx", {
    "./sidebar-item": { SidebarItemBase: Item },
  });
  const tree = api.SidebarMenuItems();
  assert.deepEqual(
    walk(tree, (n) => n.type === Item).map((n) => n.props.item.key),
    ["views", "analytics", "archives"]
  );
  const source = readFileSync(
    new URL("../core/components/workspace/sidebar/sidebar-menu-items.tsx", import.meta.url),
    "utf8"
  );
  assert.doesNotMatch(source, /MoreNavigation|toggleWorkspaceMenu|Disclosure/);
});
test("固定入口仍按工作空间角色校验，取消固定旧值无效且不渲染图钉", () => {
  for (const role of [20, 15, 5, 0]) {
    const api = load("../core/components/workspace/sidebar/sidebar-item.tsx", {
      "@/hooks/store/user": {
        useUser: () => ({ data: { id: "u" } }),
        useUserPermissions: () => ({ allowPermissions: (allowed) => allowed.includes(role) }),
      },
    });
    for (const item of items) {
      const tree = api.SidebarItemBase({ item });
      assert.equal(tree !== null, item.access.includes(role), `${role}:${item.key}`);
      if (tree) assert.equal(walk(tree, (n) => n.type === "button").length, 0);
    }
  }
});
test("自定义导航不提供三个固定入口的隐藏开关或更多说明", () => {
  const source = readFileSync(
    new URL("../core/components/navigation/customize-navigation-dialog.tsx", import.meta.url),
    "utf8"
  );
  assert.doesNotMatch(source, /workspace-pinned-items|toggleWorkspaceItem|handleWorkspaceItemToggle|更多/);
});

test("直接进入分析或归档页面同样按角色拒绝，无权限不渲染子页面", () => {
  for (const path of [
    "../app/(all)/[workspaceSlug]/(projects)/analytics/[tabId]/layout.tsx",
    "../app/(all)/[workspaceSlug]/(projects)/projects/(detail)/archives/layout.tsx",
  ]) {
    for (const role of [20, 15, 5, 0]) {
      const api = load(path, {
        "@plane/constants": {
          EUserPermissions: { ADMIN: 20, MEMBER: 15 },
          EUserPermissionsLevel: { WORKSPACE: "workspace" },
        },
        "@/hooks/store/user": { useUserPermissions: () => ({ allowPermissions: (allowed) => allowed.includes(role) }) },
        "@/components/auth-screens/not-authorized-view": { NotAuthorizedView: Denied },
      });
      const tree = api.default();
      assert.equal(tree.type === Denied, ![20, 15].includes(role));
    }
  }
});

test("合并平台导航并按常用顺序排列，当前入口有可识别的选中标记", () => {
  const menu = load("../core/components/workspace/sidebar/sidebar-menu-items.tsx");
  const tree = menu.SidebarMenuItems();
  assert.equal(walk(tree, (node) => node.props?.["aria-label"] === "平台功能").length, 1);
  const source = readFileSync(
    new URL("../core/components/workspace/sidebar/sidebar-menu-items.tsx", import.meta.url),
    "utf8"
  );
  assert.doesNotMatch(source, /common.workspace|个人功能|工作空间功能/);
  for (const selected of items) {
    const api = load("../core/components/workspace/sidebar/sidebar-item.tsx", {
      "next/navigation": {
        useParams: () => ({ workspaceSlug: "w" }),
        usePathname: () => `/w${selected.href}`,
      },
    });
    for (const item of items) {
      const itemWithHighlight = { ...item, highlight: (pathname, href) => pathname === href };
      const links = walk(api.SidebarItemBase({ item: itemWithHighlight }), (node) => !!node.props?.href);
      assert.equal(links.length, 1);
      assert.equal(links[0].props["aria-current"], item.key === selected.key ? "page" : undefined);
    }
  }
});

test("首页、我的工作、项目与统计在前，草稿便签在后，保留隐藏个人入口的偏好", () => {
  const entry = (key) => ({ ...items[0], key });
  const constants = {
    WORKSPACE_SIDEBAR_DYNAMIC_NAVIGATION_ITEMS_LINKS: items,
    WORKSPACE_SIDEBAR_STATIC_NAVIGATION_ITEMS: {
      "your-work": entry("your_work"),
      drafts: entry("drafts"),
      stickies: entry("stickies"),
    },
    WORKSPACE_SIDEBAR_STATIC_NAVIGATION_ITEMS_LINKS: [entry("home")],
    WORKSPACE_SIDEBAR_STATIC_PINNED_NAVIGATION_ITEMS_LINKS: [entry("projects")],
  };
  for (const enabled of [true, false]) {
    const api = load("../core/components/workspace/sidebar/sidebar-menu-items.tsx", {
      "./sidebar-item": { SidebarItemBase: Item },
      "@plane/constants": constants,
      "@/hooks/use-navigation-preferences": {
        usePersonalNavigationPreferences: () => ({
          preferences: {
            items: {
              your_work: { enabled, sort_order: 4 },
              drafts: { enabled, sort_order: 1 },
              stickies: { enabled, sort_order: 2 },
            },
          },
        }),
      },
    });
    assert.deepEqual(
      walk(api.SidebarMenuItems(), (node) => node.type === Item).map((node) => node.props.item.key),
      enabled
        ? ["home", "your_work", "projects", "views", "analytics", "drafts", "stickies", "archives"]
        : ["home", "projects", "views", "analytics", "archives"]
    );
  }
});

test("个人记录分组有分隔，保留用户草稿与便笺的自定义排序且归档始终最后", () => {
  const entry = (key) => ({ ...items[0], key });
  const api = load("../core/components/workspace/sidebar/sidebar-menu-items.tsx", {
    "./sidebar-item": { SidebarItemBase: Item },
    "@plane/constants": {
      WORKSPACE_SIDEBAR_DYNAMIC_NAVIGATION_ITEMS_LINKS: items,
      WORKSPACE_SIDEBAR_STATIC_NAVIGATION_ITEMS: { drafts: entry("drafts"), stickies: entry("stickies") },
      WORKSPACE_SIDEBAR_STATIC_NAVIGATION_ITEMS_LINKS: [entry("home")],
      WORKSPACE_SIDEBAR_STATIC_PINNED_NAVIGATION_ITEMS_LINKS: [entry("projects")],
    },
    "@/hooks/use-navigation-preferences": {
      usePersonalNavigationPreferences: () => ({
        preferences: {
          items: { drafts: { enabled: true, sort_order: 9 }, stickies: { enabled: true, sort_order: 2 } },
        },
      }),
    },
  });
  const tree = api.SidebarMenuItems();
  assert.deepEqual(
    walk(tree, (node) => node.type === Item).map((node) => node.props.item.key),
    ["home", "projects", "views", "analytics", "stickies", "drafts", "archives"]
  );
  assert.equal(walk(tree, (node) => node.props?.["aria-label"] === "个人记录").length, 1);
});

test("我的工作直接进入跨模块待办，个人工作项仍可从资料页查看", () => {
  const api = load("../core/components/workspace/sidebar/sidebar-item.tsx");
  const tree = api.SidebarItemBase({
    item: {
      key: "your_work",
      href: "/profile/",
      labelTranslationKey: "我的工作",
      access: [20, 15],
      highlight: () => false,
    },
  });
  assert.equal(walk(tree, (node) => node.props?.href).map((node) => node.props.href)[0], "/w/my-work/");
});

test("远程诊断固定在主侧栏统计报表之后，设置侧栏没有重复入口", () => {
  const menu = load("../core/components/workspace/sidebar/sidebar-menu-items.tsx", {
    "./sidebar-item": { SidebarItemBase: Item },
    "@/components/remote-diagnostics/navigation-item": { RemoteDiagnosticsNavigationItem: RemoteItem },
  });
  const rendered = walk(menu.SidebarMenuItems(), (node) => node.type === Item || node.type === RemoteItem).map((node) =>
    node.type === RemoteItem ? "remote-diagnostics" : node.props.item.key
  );
  assert.equal(rendered.indexOf("remote-diagnostics"), rendered.indexOf("analytics") + 1);
  const settings = readFileSync(
    new URL("../core/components/settings/workspace/sidebar/item-categories.tsx", import.meta.url),
    "utf8"
  );
  assert.doesNotMatch(settings, /remote-diagnostics/);
});

test("远程诊断主菜单仅对管理员显示并链接现有独立页面", () => {
  for (const allowed of [true, false, undefined]) {
    const api = load("../core/components/remote-diagnostics/navigation-item.tsx", {
      swr: { default: () => ({ data: allowed === undefined ? undefined : { can_manage_administrators: allowed } }) },
      "@/components/quality/api": { qualityApi: {} },
      "@/components/sidebar/sidebar-navigation": { SidebarNavItem: Nav },
      "next/navigation": {
        useParams: () => ({ workspaceSlug: "w" }),
        usePathname: () => "/w/remote-diagnostics/",
      },
    });
    const tree = api.RemoteDiagnosticsNavigationItem();
    assert.equal(tree !== null, allowed === true);
    if (tree) {
      const link = walk(tree, (node) => !!node.props?.href)[0];
      assert.equal(link.props.href, "/w/remote-diagnostics/");
      assert.equal(link.props["aria-current"], "page");
    }
  }
});
