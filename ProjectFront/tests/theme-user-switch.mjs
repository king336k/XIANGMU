import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
test("相同主题账号切换仍重新执行账号主题初始化", () => {
  let user = { id: "u1", theme: { theme: "light" } },
    cursor = 0;
  const refs = [],
    deps = [],
    effects = [],
    calls = [],
    setTheme = (value) => calls.push(value),
    params = {},
    setQuery = () => {},
    toggleSidebar = () => {};
  const mocks = {
    react: {
      useRef: (initial) => {
        const i = cursor++;
        return (refs[i] ??= { current: initial });
      },
      useEffect: (fn, values) => {
        const i = cursor++;
        if (!deps[i] || values.some((value, index) => !Object.is(value, deps[i][index]))) {
          deps[i] = values;
          effects.push(fn);
        }
      },
    },
    "mobx-react": { observer: (fn) => fn },
    "next/navigation": { useParams: () => params },
    "next-themes": { useTheme: () => ({ setTheme }) },
    "@/hooks/store/use-app-theme": { useAppTheme: () => ({ sidebarCollapsed: false, toggleSidebar }) },
    "@/hooks/store/use-router-params": { useRouterParams: () => ({ setQuery }) },
    "@/hooks/store/user": { useUserProfile: () => ({ data: user }) },
    "@/lib/local-storage": { storage: { get: () => undefined } },
    "@plane/utils": {},
  };
  const api = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL("../core/lib/wrappers/store-wrapper.tsx", import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((id) => mocks[id] || require(id), api);
  const render = () => {
    cursor = 0;
    api.default({ children: null });
    effects.splice(0).forEach((fn) => fn());
  };
  render();
  user = { id: "u2", theme: { theme: "light" } };
  render();
  assert.deepEqual(calls, ["light", "light"]);
});
