import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import vm from "node:vm";

const root = fileURLToPath(new URL("../../../../", import.meta.url));
const requireWeb = createRequire(resolve(root, "ProjectFront/package.json"));
const ts = requireWeb("typescript");
const React = requireWeb("react");
const { renderToStaticMarkup } = requireWeb("react-dom/server");
const widget = ({ children }) => React.createElement("div", null, children);
const fallback = new Proxy(widget, { get: (_, key) => (key === "__esModule" ? false : widget) });
function load(path, overrides = {}) {
  const output = ts.transpileModule(readFileSync(resolve(root, path), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    reportDiagnostics: true,
  });
  assert.equal(output.diagnostics.length, 0, path);
  const context = {
    exports: {},
    require(name) {
      if (overrides[name]) return overrides[name];
      if (name === "react" || name === "react/jsx-runtime") return requireWeb(name);
      if (name === "mobx-react") return { observer: (component) => component };
      if (name.endsWith("?url")) return "asset.svg";
      return fallback;
    },
  };
  vm.runInNewContext(output.outputText, context);
  return context.exports;
}
const render = (component, props = {}) => renderToStaticMarkup(React.createElement(component, props));
const ThemeController = ({ render: renderField }) => renderField({ field: { value: false, onChange() {} } });

test("API token and webhook empty states render Chinese", () => {
  for (const [path, name, labels, english] of [
    ["api-token/empty-state.tsx", "ApiTokenEmptyState", ["暂无 API 令牌", "添加令牌"], /No API tokens|Add token/],
    ["web-hooks/empty-state.tsx", "WebhooksEmptyState", ["暂无 Webhook", "添加 Webhook"], /No webhooks|Add webhook/],
  ]) {
    const Component = load(`ProjectFront/core/components/${path}`)[name];
    const html = render(Component, { onClick() {} });
    for (const label of labels) assert.ok(html.includes(label), html);
    assert.ok(!english.test(html), html);
  }
});

test("layout labels are Chinese and stored keys stay unchanged", () => {
  const { BASE_LAYOUTS } = load("ProjectFront/core/components/base-layouts/constants.ts");
  assert.deepEqual(
    Array.from(BASE_LAYOUTS, (item) => item.key),
    ["list", "kanban", "gantt"]
  );
  assert.deepEqual(
    Array.from(BASE_LAYOUTS, (item) => item.label),
    ["列表布局", "看板布局", "甘特图布局"]
  );
});

test("webhook event labels are Chinese while API field keys are retained", () => {
  const { INDIVIDUAL_WEBHOOK_OPTIONS } = load("ProjectFront/core/components/web-hooks/form/individual-event-options.tsx");
  assert.deepEqual(
    Array.from(INDIVIDUAL_WEBHOOK_OPTIONS, (item) => item.key),
    ["project", "cycle", "issue", "module", "issue_comment"]
  );
  assert.deepEqual(
    Array.from(INDIVIDUAL_WEBHOOK_OPTIONS, (item) => item.label),
    ["项目", "迭代", "工作项", "模块", "工作项评论"]
  );
  assert.ok(INDIVIDUAL_WEBHOOK_OPTIONS.every((item) => /[\u4e00-\u9fff]/.test(item.description)));
});

test("analytics empty option renders Chinese and keeps null value", () => {
  let emptyValue;
  const CustomSelect = ({ children }) => React.createElement("div", null, children);
  CustomSelect.Option = ({ children, value }) => {
    emptyValue = value;
    return React.createElement("span", null, children);
  };
  const { SelectXAxis } = load("ProjectFront/core/components/analytics/select/select-x-axis.tsx", {
    "@plane/ui": { CustomSelect },
  });
  const html = render(SelectXAxis, { options: [], allowNoValue: true, onChange() {} });
  assert.ok(html.includes("无值"), html);
  assert.equal(emptyValue, null);
});

test("theme modes render Chinese while radio fields retain boolean values", () => {
  const { CustomThemeModeSelector } = load("ProjectFront/core/components/core/theme/theme-mode-selector.tsx", {
    "react-hook-form": { Controller: ThemeController },
  });
  const html = render(CustomThemeModeSelector, { control: {} });
  assert.ok(html.includes("选择颜色模式"), html);
  assert.ok(html.includes("浅色模式") && html.includes("深色模式"), html);
  assert.ok(
    html.includes('name="darkPalette"') && html.includes('value="false"') && html.includes('value="true"'),
    html
  );
});

test("token status renders Chinese while preserving supplied label and description", () => {
  const { ApiTokenListItem } = load("ProjectFront/core/components/api-token/token-list-item.tsx", {
    "@/hooks/use-platform-os": { usePlatformOS: () => ({ isMobile: false }) },
    "@plane/constants": { PROFILE_SETTINGS_TRACKER_ELEMENTS: { LIST_ITEM_DELETE_ICON: "delete_token" } },
  });
  const token = Object.freeze({
    id: "token-id",
    label: "User token",
    description: "User description",
    is_active: true,
    expired_at: null,
  });
  const html = render(ApiTokenListItem, { token });
  assert.ok(html.includes("有效") && html.includes("永不过期"), html);
  assert.ok(html.includes("User token") && html.includes("User description"), html);
  assert.equal(token.is_active, true);
});
