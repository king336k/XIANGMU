import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const nodes = (tree) =>
  !tree || typeof tree !== "object"
    ? []
    : Array.isArray(tree)
      ? tree.flatMap(nodes)
      : [tree, ...nodes(tree.props?.children)];
function load(path, overrides = {}) {
  const exports = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(`../core/components/${path}`, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
    }).outputText
  )((id) => {
    if (id in overrides) return overrides[id];
    if (id === "react/jsx-runtime") return require(id);
    if (id === "react") return { useState: (x) => [typeof x === "function" ? x() : x, () => {}] };
    if (id === "mobx-react") return { observer: (x) => x };
    if (id === "@plane/utils")
      return {
        cn: (...parts) =>
          parts.flatMap((p) => (typeof p === "string" ? p : Object.keys(p).filter((k) => p[k]))).join(" "),
        renderNumericDateTime: String,
      };
    return new Proxy({}, { get: (_, key) => key });
  }, exports);
  return exports;
}
test("设置目录横向/纵向入口传达唯一当前项并提供键盘焦点", () => {
  const { SettingsSidebarItem } = load("settings/sidebar/item.tsx");
  for (const as of ["link", "button"]) {
    for (const isActive of [true, false]) {
      const tree = SettingsSidebarItem({ as, isActive, label: "成员", href: "/members", onClick() {}, iconNode: null });
      assert.equal(tree.props["aria-current"], isActive ? "page" : undefined);
      assert.match(tree.props.className, /platform-selection-item/);
    }
  }
});
test("权限弹窗 portal 的并列目录显式使用共享选中态边界", () => {
  const { MemberPermissionsModal } = load("settings/member-permissions-modal.tsx");
  const tree = MemberPermissionsModal({
    person: { id: "u", username: "user" },
    currentUserId: "admin",
    canAdmin: true,
  });
  const nav = nodes(tree).find((n) => n.type === "nav");
  assert.match(nav.props.className, /platform-selection-group/);
  const buttons = nodes(nav).filter((n) => n.type === "button");
  assert.equal(buttons.filter((n) => n.props["aria-current"] === "page").length, 1);
  const css = readFileSync(new URL("../styles/globals.css", import.meta.url), "utf8");
  assert.match(css, /\.platform-selection-group\s*\{/);
  assert.match(css, /\.platform-selection-group[^,{]*>\s*[^,{]*\[aria-current="page"\]/);
  assert.match(css, /\.platform-selection-group[^\n{]*:focus-visible/);
});
test("归档页路由参数包含周期名时仍只选中实际归档类别", () => {
  const { ArchiveTabsList } = load("archives/archive-tabs-list.tsx", {
    "next/navigation": {
      useParams: () => ({ workspaceSlug: "cycles", projectId: "modules" }),
      usePathname: () => "/cycles/projects/modules/archives/issues",
    },
    "@/hooks/store/use-project": {
      useProject: () => ({ getProjectById: () => ({ cycle_view: true, module_view: true }) }),
    },
  });
  const links = nodes(ArchiveTabsList()).filter((n) => n.type === "default");
  assert.equal(links.length, 3);
  assert.equal(links.filter((n) => n.props["aria-current"] === "page").length, 1);
  assert.match(links.find((n) => n.props["aria-current"] === "page").props.href, /archives\/issues$/);
});
test("项目更多导航中的当前页也保留选中语义", () => {
  const { TabNavigationOverflowMenu } = load("navigation/tab-navigation-overflow-menu.tsx", {
    "@plane/i18n": { useTranslation: () => ({ t: (x) => x }) },
    "@plane/propel/menu": { Menu: Object.assign(() => null, { MenuItem: "item" }) },
  });
  const tree = TabNavigationOverflowMenu({
    overflowItems: [
      { key: "a", href: "/a" },
      { key: "b", href: "/b" },
    ],
    isActive: (item) => item.key === "b",
    tabPreferences: { hiddenTabs: [] },
    onShow() {},
    onToggleDefault() {},
  });
  const links = nodes(tree).filter((n) => n.props?.to);
  assert.equal(links.length, 2);
  assert.equal(links.filter((n) => n.props["aria-current"] === "page").length, 1);
  assert.ok(links.every((n) => n.props.className.includes("platform-selection-item")));
});

test("问答会话列表明确突出当前会话和新会话", () => {
  const { AssistantConversations } = load("knowledge/assistant-conversations.tsx");
  for (const selected of ["new", "a", "b"]) {
    const tree = AssistantConversations({
      rows: [
        { id: "a", title: "A" },
        { id: "b", title: "B" },
      ],
      selected,
      drafts: {},
      onSelect() {},
      onClose() {},
    });
    const choices = nodes(tree).filter(
      (n) => n.type === "button" && n.props.className?.includes("platform-selection-item")
    );
    assert.equal(choices.length, 3);
    assert.equal(choices.filter((n) => n.props["aria-current"] === "true").length, 1);
  }
});
test("项目主导航与文档导航保留当前页语义和焦点", () => {
  const { TabNavigationVisibleItem } = load("navigation/tab-navigation-visible-item.tsx", {
    "@plane/i18n": { useTranslation: () => ({ t: (x) => x }) },
    "@plane/propel/context-menu": {
      ContextMenu: Object.assign(() => null, {
        Trigger: "trigger",
        Portal: "portal",
        Content: "content",
        Item: "item",
      }),
    },
  });
  for (const isActive of [true, false]) {
    const tree = TabNavigationVisibleItem({
      item: { key: "a", href: "/a", i18n_key: "A" },
      isActive,
      tabPreferences: {},
      onToggleDefault() {},
      onHide() {},
    });
    const link = nodes(tree).find((n) => n.props?.to === "/a");
    assert.equal(link.props["aria-current"], isActive ? "page" : undefined);
    assert.match(link.props.className, /platform-selection-item/);
  }
  const { DocumentWorkspaceNav } = load("documentation/workspace-nav.tsx");
  const tree = DocumentWorkspaceNav({ workspaceSlug: "w", projectId: "p", active: "assistant" });
  assert.match(tree.props.className, /platform-selection-group/);
  assert.equal(nodes(tree).filter((n) => n.props?.["aria-current"] === "page").length, 1);
});
