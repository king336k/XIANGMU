import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
function requests(defectsOnly, tab, withContext = true) {
  const calls = [],
    imports = [],
    exp = {},
    context = { can_write: true, business_roles_enabled: false, members: [] };
  const params = new URLSearchParams(tab ? { tab } : {});
  const source = ts.transpileModule(
    readFileSync(new URL("../core/components/quality/workbench.tsx", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }
  ).outputText;
  new Function("require", "exports", source)((id) => {
    imports.push(id);
    if (id === "react/jsx-runtime") return require(id);
    if (id === "react") return { ...React, useState: (v) => [v, () => {}], useEffect() {} };
    if (id === "react-router")
      return { useSearchParams: () => [params, () => {}], useParams: () => ({}), useLocation: () => ({ hash: "" }) };
    if (id === "@/hooks/use-resolved-project-params")
      return { useResolvedProjectParams: () => ({ workspaceSlug: "w", projectId: "p" }) };
    if (id === "swr")
      return {
        default: (key) => {
          calls.push(key);
          return { data: key?.endsWith("context/") && withContext ? context : undefined, mutate: async () => {} };
        },
        useSWRConfig: () => ({ mutate: async () => {} }),
      };
    if (id === "./types")
      return { can: () => true, canOpenQualityTab: (value) => !!value, defectDisplayTitle: (v) => v };
    if (id === "./pagination") return { normalizedPageParams: (v) => new URLSearchParams(v), pageSize: () => 20 };
    if (id === "./layout-controls") return { recordLayout: () => "table" };
    return new Proxy({}, { get: () => () => null });
  }, exp);
  exp.QualityWorkbench({ defectsOnly });
  return { calls: calls.filter(Boolean), imports };
}
test("缺陷列表只请求摘要，不启动测试报告轮询", () => {
  const { calls } = requests(true);
  assert.ok(
    calls.some((key) => key.includes("defects/?") && key.includes("summary=true")),
    calls
  );
  assert.ok(!calls.some((key) => key.endsWith("report/")), calls);
});
test("测试概览仍获取报告，其他测试页无需加载报告", () => {
  assert.ok(requests(false, "overview").calls.some((key) => key.endsWith("report/")));
  assert.ok(!requests(false, "plans").calls.some((key) => key.endsWith("report/")));
});
test("详情、统计和报告面板不进入缺陷列表的同步依赖", () => {
  const { imports } = requests(true);
  for (const file of [
    "./defect-form",
    "./reports-panel",
    "./defect-statistics",
    "./quality-summary",
    "./quality-record-peek",
  ])
    assert.ok(!imports.includes(file), file);
});

test("缺陷列表与上下文并行读取，权限仍由服务端校验", () => {
  assert.ok(requests(true, undefined, false).calls.some((key) => key.includes("defects/?")));
});
