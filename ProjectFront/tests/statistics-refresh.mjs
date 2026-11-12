import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
test("缺陷报表打开时定时重新取数，DAQ新增或他人处理不会长期停留在缓存0", () => {
  const exports = {},
    calls = [];
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/quality/defect-statistics.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
    ).outputText
  )(
    (id) =>
      id === "swr"
        ? {
            default: (...args) => {
              calls.push(args);
              return {};
            },
          }
        : id === "react/jsx-runtime"
          ? require(id)
          : new Proxy({}, { get: () => () => null }),
    exports
  );
  exports.DefectStatistics({
    base: "/q/",
    params: new URLSearchParams("panel=statistics&page=2&view=unclosed"),
    onFilter() {},
  });
  assert.equal(calls[0][0], "/q/defect-statistics/?view=unclosed");
  assert.ok(calls[0][2]?.refreshInterval > 0 && calls[0][2].refreshInterval <= 15000);
  assert.equal(calls[0][2].revalidateOnMount, true);
});
