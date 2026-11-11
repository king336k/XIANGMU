import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
function load(path, mocks = {}) {
  const api = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((id) => mocks[id] || require(id), api);
  return api;
}
const missing = () => {
  throw Error("storage denied");
};
test("浏览器禁止存储时读取损坏偏好安全返回默认值，写入移除不阻断界面", () => {
  const previous = globalThis.window;
  globalThis.window = { localStorage: { getItem: missing, setItem: missing, removeItem: missing } };
  try {
    const hooks = load("../core/hooks/use-local-storage.tsx", { react: {} }),
      plain = load("../core/lib/local-storage.ts", {
        "lodash-es": { isEmpty: (value) => !value || Object.keys(value).length === 0 },
      }).storage;
    assert.doesNotThrow(() => assert.equal(hooks.getValueFromLocalStorage("theme", "light"), "light"));
    assert.equal(hooks.setValueIntoLocalStorage("theme", "dark"), false);
    assert.doesNotThrow(() => assert.equal(plain.get("theme"), undefined));
    assert.doesNotThrow(() => plain.set("theme", "dark"));
    assert.doesNotThrow(() => plain.remove("theme"));
  } finally {
    if (previous === undefined) delete globalThis.window;
    else globalThis.window = previous;
  }
});
test("关闭类布尔偏好能够持久保存false，损坏JSON仅清除当前键", () => {
  const previous = globalThis.window,
    values = new Map([
      ["broken", "{"],
      ["other", "preserved"],
    ]);
  globalThis.window = {
    localStorage: {
      getItem: (key) => values.get(key),
      setItem: (key, value) => values.set(key, value),
      removeItem: (key) => values.delete(key),
    },
  };
  try {
    const hooks = load("../core/hooks/use-local-storage.tsx", { react: {} }),
      plain = load("../core/lib/local-storage.ts", {
        "lodash-es": { isEmpty: (value) => !value || Object.keys(value).length === 0 },
      }).storage;
    plain.set("collapsed", false);
    assert.equal(plain.get("collapsed"), "false");
    assert.equal(hooks.getValueFromLocalStorage("broken", "fallback"), "fallback");
    assert.equal(values.has("broken"), false);
    assert.equal(values.get("other"), "preserved");
  } finally {
    if (previous === undefined) delete globalThis.window;
    else globalThis.window = previous;
  }
});
test("无window时存储帮助方法不访问浏览器", () => {
  const previous = globalThis.window;
  delete globalThis.window;
  try {
    const hooks = load("../core/hooks/use-local-storage.tsx", { react: {} }),
      plain = load("../core/lib/local-storage.ts", { "lodash-es": { isEmpty: () => false } }).storage;
    assert.equal(hooks.getValueFromLocalStorage("x", 5), 5);
    assert.equal(hooks.setValueIntoLocalStorage("x", 5), false);
    assert.equal(plain.get("x"), undefined);
    assert.doesNotThrow(() => plain.set("x", false));
    assert.doesNotThrow(() => plain.remove("x"));
  } finally {
    if (previous !== undefined) globalThis.window = previous;
  }
});

test("启动包装器在存储禁用时仍能完成侧栏初始化", () => {
  const previousWindow = globalThis.window,
    previousStorage = Object.getOwnPropertyDescriptor(globalThis, "localStorage"),
    effects = [];
  const blocked = { getItem: missing, setItem: missing, removeItem: missing };
  globalThis.window = { localStorage: blocked };
  Object.defineProperty(globalThis, "localStorage", { value: blocked, configurable: true });
  try {
    const mocks = {
      react: { useEffect: (fn) => effects.push(fn), useRef: (value) => ({ current: value }) },
      "mobx-react": { observer: (fn) => fn },
      "next/navigation": { useParams: () => ({}) },
      "next-themes": { useTheme: () => ({ setTheme() {} }) },
      "@/hooks/store/use-app-theme": { useAppTheme: () => ({ sidebarCollapsed: undefined, toggleSidebar() {} }) },
      "@/hooks/store/use-router-params": { useRouterParams: () => ({ setQuery() {} }) },
      "@/hooks/store/user": { useUserProfile: () => ({ data: undefined }) },
      "@plane/utils": {},
      "@/lib/local-storage": load("../core/lib/local-storage.ts", { "lodash-es": { isEmpty: () => false } }),
    };
    const module = load("../core/lib/wrappers/store-wrapper.tsx", mocks);
    module.default({ children: null });
    assert.doesNotThrow(() => effects.forEach((fn) => fn()));
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousStorage) Object.defineProperty(globalThis, "localStorage", previousStorage);
    else delete globalThis.localStorage;
  }
});

test("存储被禁用时各侧栏仍可折叠展开并准确更新内存状态", () => {
  const originalWindow = globalThis.window,
    originalStorage = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  const blocked = { getItem: missing, setItem: missing, removeItem: missing };
  globalThis.window = { localStorage: blocked };
  Object.defineProperty(globalThis, "localStorage", { value: blocked, configurable: true });
  try {
    const safe = load("../core/lib/local-storage.ts", { "lodash-es": { isEmpty: () => false } });
    const { ThemeStore } = load("../core/store/theme.store.ts", { "@/lib/local-storage": safe });
    const theme = new ThemeStore();
    for (const [method, field] of [
      ["toggleSidebar", "sidebarCollapsed"],
      ["toggleExtendedSidebar", "isExtendedSidebarOpened"],
      ["toggleExtendedProjectSidebar", "isExtendedProjectSidebarOpened"],
      ["toggleProfileSidebar", "profileSidebarCollapsed"],
      ["toggleWorkspaceAnalyticsSidebar", "workspaceAnalyticsSidebarCollapsed"],
      ["toggleIssueDetailSidebar", "issueDetailSidebarCollapsed"],
      ["toggleEpicDetailSidebar", "epicDetailSidebarCollapsed"],
      ["toggleInitiativesSidebar", "initiativesSidebarCollapsed"],
      ["toggleProjectOverviewSidebar", "projectOverviewSidebarCollapsed"],
    ]) {
      assert.doesNotThrow(() => theme[method](true), method);
      assert.equal(theme[field], true);
      assert.doesNotThrow(() => theme[method](false), method);
      assert.equal(theme[field], false);
    }
  } finally {
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
    if (originalStorage) Object.defineProperty(globalThis, "localStorage", originalStorage);
    else delete globalThis.localStorage;
  }
});
