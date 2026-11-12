import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
function load(path, mocks) {
  const exp = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(`../${path}`, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
    }).outputText
  )((id) => mocks[id] || (id === "react/jsx-runtime" ? require(id) : new Proxy({}, { get: () => () => null })), exp);
  return exp;
}
function nodes(t) {
  return !t || typeof t !== "object" ? [] : Array.isArray(t) ? t.flatMap(nodes) : [t, ...nodes(t.props?.children)];
}
test("删除便签的确认按钮说明实际操作，不落入共用英文默认值", () => {
  const tree = load("core/components/stickies/delete-modal.tsx", {
    react: { useState: () => [false, () => {}] },
    "mobx-react": { observer: (f) => f },
    "@plane/i18n": { useTranslation: () => ({ t: (k) => k }) },
  }).StickyDeleteModal({ isOpen: true, handleSubmit: async () => {}, handleClose() {} });
  assert.deepEqual(tree.props.primaryButtonText, { loading: "正在删除…", default: "删除便签" });
  assert.equal(tree.props.secondaryButtonText, "取消");
});
test("便签空页不再嵌入带英文示例内容的宣传截图", () => {
  const exp = load("core/components/stickies/layout/stickies-list.tsx", {
    react: {
      useState: () => [0, () => {}],
      useCallback: (f) => f,
      useEffect() {},
      useMemo: (f) => f(),
      useRef: () => ({ current: null }),
    },
    "mobx-react": { observer: (f) => f },
    "next-themes": { useTheme: () => ({ resolvedTheme: "light" }) },
    "next/navigation": { useParams: () => ({ workspaceSlug: "w" }), usePathname: () => "/w/stickies/" },
    "@plane/i18n": { useTranslation: () => ({ t: (k) => k }) },
    "@/hooks/use-stickies": {
      useSticky: () => ({ loader: "loaded", getWorkspaceStickyIds: () => [], searchQuery: "" }),
    },
    "@/hooks/store/user": { useUserPermissions: () => ({ allowPermissions: () => true }) },
    "../sticky/use-operations": { useStickyOperations: () => ({ stickyOperations: {} }) },
    "@plane/types": { EUserWorkspaceRoles: { ADMIN: 20, MEMBER: 15, GUEST: 5 } },
    "@plane/constants": { EUserPermissions: { GUEST: 5 }, EUserPermissionsLevel: { WORKSPACE: "WORKSPACE" } },
  });
  const component = exp.StickiesList || exp.WorkspaceStickiesList;
  assert.equal(typeof component, "function");
  const tree = component({ workspaceSlug: "w" });
  const empty = nodes(tree).find((n) => n.props?.primaryButton);
  assert.equal(empty?.props.assetPath, undefined);
});

test("项目筛选分组使用业务名称，中文关键词能找到可见范围", () => {
  const items = [
    { key: 0, i18n_label: "workspace_projects.network.private.title", iconKey: "private" },
    { key: 2, i18n_label: "workspace_projects.network.public.title", iconKey: "public" },
  ];
  const tree = load("core/components/project/dropdowns/filters/access.tsx", {
    react: { useState: () => [true, () => {}] },
    "mobx-react": { observer: (f) => f },
    "@plane/constants": { NETWORK_CHOICES: items },
    "@plane/i18n": { useTranslation: () => ({ t: (k) => (k.includes(".private.") ? "仅项目成员" : "工作空间可见") }) },
  }).FilterAccess({ appliedFilters: null, handleUpdate() {}, searchQuery: "仅项目成员" });
  assert.equal(nodes(tree).find((n) => "isPreviewEnabled" in (n.props || {})).props.title, "可见范围");
  assert.equal(nodes(tree).filter((n) => "isChecked" in (n.props || {})).length, 1);
});

test("便签读取和删除直接请求正确路由，不依赖后端重定向", async () => {
  const calls = [];
  const exp = load("core/services/sticky.service.ts", {
    "@plane/constants": { API_BASE_URL: "", STICKIES_PER_PAGE: 30 },
    "@/services/api.service": {
      APIService: class {
        get(path) {
          calls.push(["get", path]);
          return Promise.resolve({ data: {} });
        }
        delete(path) {
          calls.push(["delete", path]);
          return Promise.resolve({ data: {} });
        }
      },
    },
  });
  const service = new exp.StickyService();
  await service.getSticky("w", "s");
  await service.deleteSticky("w", "s");
  assert.deepEqual(calls, [
    ["get", "/api/workspaces/w/stickies/s/"],
    ["delete", "/api/workspaces/w/stickies/s/"],
  ]);
});
