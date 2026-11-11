import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
function load(path, mocks = {}) {
  const api = {};
  const code = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  new Function("require", "exports", code)((name) => mocks[name] || require(name), api);
  return api;
}
test("前置主题入口只打开原设置，不改变主题或缩减功能", () => {
  let opened = 0;
  const Item = () => null;
  const { ThemeShortcuts } = load("../core/components/appearance/theme-shortcuts.tsx", {
    "@plane/ui": { CustomMenu: { MenuItem: Item } },
  });
  const button = ThemeShortcuts({ onOpen: () => opened++ });
  assert.equal(button.type, Item);
  button.props.onClick();
  assert.equal(opened, 1);
});
test("主题设置复用原完整组件，不显示其他偏好控件", () => {
  const Original = () => null;
  const { PreferencesProfileSettings } = load(
    "../core/components/settings/profile/content/pages/preferences/root.tsx",
    { "./default-list": { ProfileSettingsDefaultPreferencesList: Original } }
  );
  const tree = PreferencesProfileSettings();
  assert.equal(tree.props.children.type, Original);
  assert.equal(tree.props["aria-label"], "主题");
});
test("原主题选择保留系统、浅深色、高对比度和自定义选项", () => {
  const constants = load("../../packages/constants/src/themes.ts");
  const Select = () => null;
  Select.Option = () => null;
  const { ThemeSwitch } = load("../core/components/core/theme/theme-switch.tsx", {
    "@plane/constants": constants,
    "@plane/i18n": { useTranslation: () => ({ t: (x) => x }) },
    "@plane/ui": { CustomSelect: Select },
  });
  const tree = ThemeSwitch({ value: constants.THEME_OPTIONS[0], onChange: () => {} });
  assert.deepEqual(
    tree.props.children.map((option) => option.props.value.value),
    ["system", "light", "dark", "light-contrast", "dark-contrast", "custom"]
  );
});
test("自定义主题仍显示原配色及配置导入导出面板", () => {
  const React = require("react"),
    OriginalCustom = () => null;
  const { ThemeSwitcher } = load("../core/components/appearance/theme-switcher.tsx", {
    react: { ...React, useMemo: (fn) => fn(), useCallback: (fn) => fn },
    "mobx-react": { observer: (fn) => fn },
    "next-themes": { useTheme: () => ({ setTheme: () => {} }) },
    "@plane/constants": load("../../packages/constants/src/themes.ts"),
    "@plane/i18n": { useTranslation: () => ({ t: (x) => x }) },
    "@plane/propel/toast": { setPromiseToast: () => {} },
    "@plane/utils": { applyCustomTheme: () => {} },
    "@/components/core/theme/custom-theme-selector": { CustomThemeSelector: OriginalCustom },
    "@/components/core/theme/theme-switch": { ThemeSwitch: () => null },
    "@/components/settings/control-item": { SettingsControlItem: () => null },
    "@/hooks/store/user": {
      useUserProfile: () => ({ data: { theme: { theme: "custom" } }, updateUserTheme: () => {} }),
    },
  });
  const tree = ThemeSwitcher({ option: { id: "theme", title: "theme", description: "" } });
  assert.equal(tree.props.children[1].type, OriginalCustom);
});

test("主题预览卡片保留全部选项并直接选择对应主题", () => {
  const constants = load("../../packages/constants/src/themes.ts"),
    selected = [];
  const { ThemeSwitch } = load("../core/components/core/theme/theme-switch.tsx", {
    "@plane/constants": constants,
    "@plane/i18n": { useTranslation: () => ({ t: (x) => x }) },
    "@plane/ui": { CustomSelect: () => null },
  });
  const tree = ThemeSwitch({
    value: constants.THEME_OPTIONS[1],
    onChange: (option) => selected.push(option.value),
    presentation: "cards",
  });
  assert.equal(tree.props.role, "group");
  assert.equal(tree.props.children.length, 6);
  tree.props.children[4].props.onClick();
  assert.deepEqual(selected, ["dark-contrast"]);
  assert.equal(tree.props.children[1].props["aria-pressed"], true);
  assert.equal(tree.props.children[0].props["aria-pressed"], false);
});

function profileModalHarness() {
  const React = require("react"),
    state = { activeTab: "general", isOpen: true },
    refs = [];
  let cursor = 0;
  const Modal = () => null,
    Content = () => null,
    Sidebar = () => null;
  const { ProfileSettingsModal } = load("../core/components/settings/profile/modal.tsx", {
    react: { ...React, useCallback: (fn) => fn, useRef: (value) => (refs[cursor++] ||= { current: value }) },
    "mobx-react": { observer: (fn) => fn },
    "@plane/propel/icon-button": { IconButton: () => null },
    "@plane/ui": {
      ModalCore: Modal,
      EModalPosition: { CENTER: "center" },
      EModalWidth: { XL: "compact", VIXL: "full" },
    },
    "@/hooks/store/use-command-palette": {
      useCommandPalette: () => ({
        profileSettingsModal: state,
        toggleProfileSettingsModal: (value) => Object.assign(state, value),
      }),
    },
    "./content": { ProfileSettingsContent: Content },
    "./sidebar": { ProfileSettingsSidebarRoot: Sidebar },
    "./content/pages/preferences/root": { PreferencesProfileSettings: () => null },
  });
  return {
    state,
    render: () => {
      cursor = 0;
      return ProfileSettingsModal();
    },
  };
}

test("从个人资料打开主题，关闭后返回原设置页而非关闭整个设置", () => {
  for (const tab of ["general", "security"]) {
    const { state, render } = profileModalHarness();
    state.activeTab = tab;
    const settings = render();
    settings.props.children.props.children[0].props.children[0].props.updateActiveTab("preferences");
    const theme = render();
    assert.equal(theme.props.width, "compact");
    theme.props.handleClose();
    assert.equal(state.isOpen, true);
    assert.equal(state.activeTab, tab);
  }
});

test("账号菜单直接打开主题，关闭仅结束该弹窗", () => {
  const { state, render } = profileModalHarness();
  state.activeTab = "preferences";
  render().props.handleClose();
  assert.equal(state.isOpen, false);
});
