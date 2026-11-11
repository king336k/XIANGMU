import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
test("按周期模块分组先加载真实选项，状态分组不发无关请求", async () => {
  const calls = [],
    api = {};
  const mocks = {
    swr: {
      default: (key, fn) => {
        if (key) calls.push(fn());
        return { isLoading: false };
      },
    },
    "next/navigation": { useParams: () => ({ workspaceSlug: "w", projectId: "p" }) },
    "@/hooks/store/use-cycle": {
      useCycle: () => ({
        fetchAllCycles: async (w, p) => {
          calls.push(["cycles", w, p]);
        },
      }),
    },
    "@/hooks/store/use-module": {
      useModule: () => ({
        fetchModules: async (w, p) => {
          calls.push(["modules", w, p]);
        },
      }),
    },
  };
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL("../core/hooks/use-issue-group-lookups.ts", import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText
  )((id) => mocks[id], api);
  api.useIssueGroupLookups("cycle", "module");
  await Promise.all(calls.filter((x) => x instanceof Promise));
  assert.ok(calls.some((x) => Array.isArray(x) && x[0] === "cycles"));
  assert.ok(calls.some((x) => Array.isArray(x) && x[0] === "modules"));
  const previous = calls.length;
  api.useIssueGroupLookups("state");
  assert.equal(calls.length, previous);
  assert.deepEqual(api.issueGroupLookupKinds("cycle", "cycle"), ["cycle"]);
});
