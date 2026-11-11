import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const repoFile = (path) => readFileSync(new URL(`../../${path}`, import.meta.url), "utf8");
function load(path, mocks) {
  const exports = {};
  const code = ts.transpileModule(repoFile(path), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  new Function("require", "exports", code)(
    (id) => mocks[id] ?? (id === "react/jsx-runtime" ? require(id) : new Proxy({}, { get: () => () => null })),
    exports
  );
  return exports;
}
function literals(path) {
  const found = [];
  const tree = ts.createSourceFile(path, repoFile(path), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  function visit(node) {
    if (ts.isStringLiteral(node) || ts.isJsxText(node)) found.push(node.text.trim());
    ts.forEachChild(node, visit);
  }
  visit(tree);
  return found;
}
test("共享搜索选择器默认提示为中文，不再出现Search和No matches found", () => {
  const select = literals("packages/ui/src/dropdowns/custom-search-select.tsx");
  assert.ok(select.includes("搜索"));
  assert.ok(select.includes("没有匹配结果"));
  assert.ok(select.includes("加载中…"));
  assert.ok(!select.includes("Search") && !select.includes("No matches found") && !select.includes("Loading..."));
  assert.ok(literals("packages/ui/src/dropdown/common/options.tsx").includes("没有匹配结果"));
});
test("通用搜索输入保留调用方文案，缺省使用搜索", () => {
  const { InputSearch } = load("packages/ui/src/dropdown/common/input-search.tsx", {
    react: { ...React, useEffect() {}, useRef: () => ({ current: null }) },
    "../../utils": { cn: () => "" },
    "@headlessui/react": { Combobox: { Input: () => null } },
  });
  const props = { isOpen: true, query: "", updateQuery() {}, isMobile: false };
  assert.equal(InputSearch(props).props.children[1].props.placeholder, "搜索");
  assert.equal(InputSearch({ ...props, inputPlaceholder: "搜索成员" }).props.children[1].props.placeholder, "搜索成员");
});
test("表情搜索提供具体中文占位文案且允许覆盖", () => {
  const { EmojiReactionPicker } = load("packages/propel/src/emoji-reaction/emoji-reaction-picker.tsx", {
    react: { ...React, useMemo: (fn) => fn(), useCallback: (fn) => fn },
    "../popover": { Popover: Object.assign(() => null, { Button: () => null, Panel: () => null }) },
    "../utils/placement": { convertPlacementToSideAndAlign: () => ({ side: "bottom", align: "start" }) },
  });
  const props = { isOpen: true, handleToggle() {}, label: "表情", onChange() {} };
  const placeholder = (data) =>
    EmojiReactionPicker(data).props.children[1].props.children.props.children.props.searchPlaceholder;
  assert.equal(placeholder(props), "搜索表情");
  assert.equal(placeholder({ ...props, searchPlaceholder: "查找反应" }), "查找反应");
});
test("文档空态只保留必要标题和创建按钮，不含营销说明", () => {
  const data = JSON.parse(repoFile("packages/i18n/src/locales/zh-CN/empty-state.json"));
  for (const page of [data.project_empty_state.pages, data.workspace_empty_state.wiki]) {
    assert.equal(page.title, "还没有文档");
    assert.equal(page.description, "");
    assert.equal(page.cta_primary, "新建文档");
  }
  assert.equal(data.project_empty_state.cycles.title, "还没有周期");
  assert.equal(data.common_empty_state.search.title, "没有匹配结果");
  assert.doesNotMatch(data.common_empty_state.server_error.description, /正在处理|请放心/);
});

test("其他共享搜索入口和加载提示也使用中文缺省文案", () => {
  const expected = {
    "packages/propel/src/combobox/combobox.tsx": "没有匹配结果",
    "packages/propel/src/emoji-icon-picker/emoji-picker.tsx": "搜索表情",
    "packages/propel/src/emoji-icon-picker/emoji/emoji.tsx": "搜索表情",
    "packages/propel/src/emoji-icon-picker/icon/icon-root.tsx": "搜索图标",
    "packages/ui/src/spinners/circular-spinner.tsx": "加载中…",
    "packages/propel/src/spinners/circular-spinner.tsx": "加载中…",
    "packages/propel/src/toast/toast.tsx": "处理中…",
    "ProjectFront/core/components/project/member-list.tsx": "搜索成员",
    "ProjectFront/core/components/project/dropdowns/filters/root.tsx": "搜索筛选项",
  };
  for (const [path, text] of Object.entries(expected))
    assert.ok(literals(path).includes(text), `${path} 应显示 ${text}`);
});
test("集成设置标签用中文说明，保留协议名和品牌名", () => {
  const integration = JSON.parse(repoFile("packages/i18n/src/locales/zh-CN/integration.json"));
  assert.equal(integration.github_integration.name, "GitHub");
  assert.equal(integration.github_enterprise_integration.client_secret_title, "客户端密钥");
  assert.equal(JSON.parse(repoFile("packages/i18n/src/locales/zh-CN/common.json")).forum, "论坛");
});
test("内部导航标识仍按原值传递，不受界面文案清查影响", () => {
  assert.ok(repoFile("ProjectFront/app/(all)/[workspaceSlug]/(projects)/sidebar.tsx").includes('title="Projects"'));
});

test("真实翻译引擎允许空态省略描述，不回退英文营销段落", async () => {
  const i18next = createRequire(new URL("../../packages/i18n/package.json", import.meta.url))("i18next");
  const instance = i18next.createInstance();
  await instance.init({
    showSupportNotice: false,
    lng: "zh-CN",
    fallbackLng: "en",
    returnEmptyString: false,
    resources: {
      "zh-CN": { translation: JSON.parse(repoFile("packages/i18n/src/locales/zh-CN/empty-state.json")) },
      en: { translation: JSON.parse(repoFile("packages/i18n/src/locales/en/empty-state.json")) },
    },
  });
  // With the project's configuration, an empty locale value falls back to English.
  assert.match(instance.t("project_empty_state.pages.description"), /Pages let you/);
  for (const [available, pageType] of [
    [false, "public"],
    [true, "public"],
    [true, "private"],
    [true, "archived"],
  ]) {
    const calls = [];
    const { PagesListMainContent } = load("ProjectFront/core/components/pages/pages-list-main-content.tsx", {
      react: { ...React, useState: (value) => [value, () => {}] },
      "mobx-react": { observer: (fn) => fn },
      "next/navigation": { useRouter: () => ({}), useParams: () => ({ workspaceSlug: "test" }) },
      "@plane/constants": { EUserPermissionsLevel: { PROJECT: "project" } },
      "@plane/types": { EUserProjectRoles: { ADMIN: 1, MEMBER: 2 } },
      "@plane/i18n": {
        useTranslation: () => ({
          t: (key) => {
            calls.push(key);
            return instance.t(key);
          },
        }),
      },
      "@/hooks/store/use-project": { useProject: () => ({ currentProjectDetails: { id: "p" } }) },
      "@/hooks/store/user": { useUserPermissions: () => ({ allowPermissions: () => true }) },
      "@/hooks/store": {
        EPageStoreType: { PROJECT: "project" },
        usePageStore: () => ({
          isAnyPageAvailable: available,
          getCurrentProjectFilteredPageIdsByTab: () => [],
          getCurrentProjectPageIdsByTab: () => [],
          canCurrentUserCreatePage: true,
        }),
      },
    });
    const result = PagesListMainContent({ pageType, storeType: "project" });
    assert.equal(result.props.description, undefined);
    assert.ok(calls.every((key) => !key.endsWith(".description")));
    if (pageType !== "archived") {
      assert.equal(result.props.title, "还没有文档");
      assert.equal(result.props.actions[0].label, "新建文档");
    }
  }
});

test("新账号首页便签与最近访问空态简洁且不误称全部为项目", () => {
  const stickies = JSON.parse(repoFile("packages/i18n/src/locales/zh-CN/stickies.json")).stickies;
  const recents = JSON.parse(repoFile("packages/i18n/src/locales/zh-CN/home.json")).home.recents;
  assert.equal(stickies["no-data"], "还没有便签");
  assert.equal(stickies.empty_state.simple, "还没有便签");
  assert.equal(stickies.add, "添加便签");
  assert.equal(recents.empty.default, "还没有最近访问记录");
});
