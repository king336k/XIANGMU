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
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText
  )((id) => mocks[id] || require(id), api);
  return api;
}
test("浏览器禁止本地存储时，布局菜单与看板仍同步，且不会串到其他账号", () => {
  const originalWindow = globalThis.window,
    originalStorage = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  globalThis.window = new EventTarget();
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: {
      getItem() {
        throw new Error("blocked");
      },
      setItem() {
        throw new Error("blocked");
      },
    },
  });
  const cleanups = [];
  try {
    const helpers = load("../core/components/issues/issue-layouts/kanban/arrangement.ts");
    function instance(user) {
      let value;
      const effects = [];
      const { useBoardArrangement } = load("../core/components/issues/issue-layouts/kanban/use-arrangement.ts", {
        react: {
          useState: () => [
            value,
            (next) => {
              value = next;
            },
          ],
          useCallback: (fn) => fn,
          useEffect: (fn) => effects.push(fn),
        },
        "next/navigation": { usePathname: () => "/w/p/APP/issues/" },
        "@/hooks/store/user": { useUser: () => ({ data: { id: user } }) },
        "./arrangement": helpers,
      });
      const render = () => useBoardArrangement("state");
      render();
      cleanups.push(effects.shift()());
      return render;
    }
    const menu = instance("u1"),
      board = instance("u1"),
      other = instance("u2");
    menu().update({ layout: "two-columns", order: ["closed", "open"] });
    assert.equal(board().layout, "two-columns");
    assert.deepEqual(board().order, ["closed", "open"]);
    assert.equal(other().layout, "horizontal");
    assert.deepEqual(other().order, []);
  } finally {
    cleanups.forEach((fn) => fn?.());
    globalThis.window = originalWindow;
    if (originalStorage) Object.defineProperty(globalThis, "localStorage", originalStorage);
    else delete globalThis.localStorage;
  }
});
