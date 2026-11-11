import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
function boot() {
  const calls = [],
    listeners = [],
    container = { kind: "app-subtree" },
    document = { getElementById: (id) => (id === "platform-root" ? container : null) };
  const mocks = {
    react: { startTransition: (fn) => fn(), StrictMode: () => null },
    "react-dom/client": {
      hydrateRoot: (target, tree) => calls.push({ method: "hydrate", target, tree }),
      createRoot: (target) => ({ render: (tree) => calls.push({ method: "render", target, tree }) }),
    },
    "react-router/dom": { HydratedRouter: () => null },
    "@/lib/polyfills": {},
    "@/lib/stale-asset-error": { isStaleAssetErrorMessage: () => false, recoverFromStaleAsset: () => false },
  };
  const source = readFileSync(new URL("../app/entry.client.tsx", import.meta.url), "utf8").replaceAll(
    "import.meta.env.PROD",
    "true"
  );
  new Function(
    "exports",
    "require",
    "document",
    "window",
    ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } })
      .outputText
  )({}, (id) => mocks[id] || require(id), document, { addEventListener: (event, fn) => listeners.push(event) });
  return { calls, listeners, document, container };
}
test("静态单页应用按客户端挂载，不对包含外部节点的文档执行SSR接管", () => {
  const result = boot();
  assert.equal(result.calls.length, 1);
  assert.equal(result.calls[0].method, "render");
  assert.equal(result.calls[0].target, result.container);
  assert.ok(result.calls[0].tree);
});
test("静态资源更新恢复监听保持完整", () => {
  assert.deepEqual(boot().listeners, ["vite:preloadError", "error", "unhandledrejection"]);
});
