import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const widget = ({ children }) => React.createElement("div", null, children);
const root = new URL("../core/components/", import.meta.url);
test("首次访问和退出后的默认语言为简体中文", () => {
  const source = readFileSync(new URL("../../packages/i18n/src/constants/language.ts", import.meta.url), "utf8");
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const exports = {};
  new Function("exports", code)(exports);
  assert.equal(exports.FALLBACK_LANGUAGE, "zh-CN");
});
test("自定义导航弹窗的说明、模式说明、数量错误全部为中文", () => {
  const path = new URL("navigation/customize-navigation-dialog.tsx", root);
  const code = ts.transpileModule(readFileSync(path, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const exports = {};
  const preferences = { items: {}, navigationMode: "ACCORDION", showLimitedProjects: true, limitedProjectsCount: 0 };
  const hooks = new Proxy({}, { get: () => () => ({ preferences }) });
  new Function("require", "exports", code)((id) => {
    if (id === "react" || id === "react/jsx-runtime" || id === "lucide-react") return require(id);
    if (id === "mobx-react") return { observer: (component) => component };
    if (id === "next/navigation") return { useParams: () => ({ workspaceSlug: "test" }) };
    if (id === "@plane/constants") return { WORKSPACE_SIDEBAR_DYNAMIC_NAVIGATION_ITEMS_LINKS: [] };
    if (id === "@plane/i18n") return { useTranslation: () => ({ t: () => "中文" }) };
    if (id === "@plane/ui")
      return { ModalCore: widget, Checkbox: () => null, Sortable: () => null, EModalPosition: {}, EModalWidth: {} };
    if (id === "@plane/utils") return { cn: () => "" };
    if (id === "@/components/workspace/sidebar/helper") return { getSidebarNavigationItemIcon: () => null };
    if (id === "@/hooks/store/user") return { useUserPermissions: () => ({ allowPermissions: () => true }) };
    if (id === "@/hooks/use-navigation-preferences") return hooks;
    return {};
  }, exports);
  const html = renderToStaticMarkup(
    React.createElement(exports.CustomizeNavigationDialog, { isOpen: true, onClose() {} })
  );
  assert.ok(!/Selected items|Feature tabs|Minimum value/.test(html), html);
  assert.ok(html.includes("仅对你生效"), html);
  assert.ok(html.includes("至少显示 1 个项目"), html);
});
