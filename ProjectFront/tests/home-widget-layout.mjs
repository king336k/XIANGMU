import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
function widgets(order, enabled) {
  const api = {},
    mocks = {
      "mobx-react": { observer: (fn) => fn },
      "next/navigation": { useParams: () => ({ workspaceSlug: "w" }), usePathname: () => "/w/" },
      "next-themes": { useTheme: () => ({ resolvedTheme: "light" }) },
      "@plane/i18n": { useTranslation: () => ({ t: (key) => key }) },
      "@/hooks/store/use-home": {
        useHome: () => ({
          orderedWidgets: order,
          widgetsMap: Object.fromEntries(enabled.map((k) => [k, { is_enabled: true }])),
          isAnyWidgetEnabled: true,
          loading: false,
        }),
      },
      "@/hooks/store/use-project": { useProject: () => ({ loader: "loaded" }) },
    };
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/home/home-dashboard-widgets.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
    ).outputText
  )((id) => mocks[id] || (id === "react/jsx-runtime" ? require(id) : new Proxy({}, { get: () => () => null })), api);
  return api.DashboardWidgets().props.children[2].props.children;
}
test("首页宽屏分栏保留组件顺序和启用设置，最近与便签分配主次宽度", () => {
  const order = ["quick_links", "recents", "my_stickies"],
    before = [...order],
    nodes = widgets(order, order);
  assert.deepEqual(
    nodes.map((n) => n.props["data-home-widget"]),
    order
  );
  assert.match(nodes[0].props.className, /@4xl:col-span-2/);
  assert.match(nodes[1].props.className, /@4xl:col-span-1/);
  assert.match(nodes[2].props.className, /@4xl:col-span-1/);
  assert.deepEqual(order, before);
});
test("隐藏便签后最近访问占满可用宽度，不留下空侧栏", () => {
  const nodes = widgets(["recents", "my_stickies"], ["recents"]);
  assert.equal(nodes.length, 1);
  assert.match(nodes[0].props.className, /@4xl:col-span-1/);
});
