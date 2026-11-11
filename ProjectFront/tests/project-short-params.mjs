import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
function resolve(params) {
  const code = ts.transpileModule(
    readFileSync(new URL("../core/hooks/use-resolved-project-params.ts", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS } }
  ).outputText;
  const exports = {};
  const routeApi = {};
  new Function(
    "exports",
    ts.transpileModule(readFileSync(new URL("../helpers/project-route.ts", import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS },
    }).outputText
  )(routeApi);
  new Function("require", "exports", code)(
    () => ({
      useParams: () =>
        routeApi.resolveProjectRouteParams(params, [{ id: "uuid-project", identifier: "DEMO", workspace: "ws" }], "ws"),
    }),
    exports
  );
  return exports.useResolvedProjectParams();
}
test("短项目编号只解析为接口UUID，保留工作空间和URL参数语义", () =>
  assert.deepEqual(resolve({ workspaceSlug: "work", projectCode: "demo", section: "versions" }), {
    workspaceSlug: "work",
    projectCode: "demo",
    section: "versions",
    projectId: "uuid-project",
  }));
test("原UUID链接保持兼容，未知项目编号不指向其他项目", () => {
  assert.equal(
    resolve({ workspaceSlug: "work", projectId: "00000000-0000-0000-0000-000000000001" }).projectId,
    "00000000-0000-0000-0000-000000000001"
  );
  assert.equal(resolve({ workspaceSlug: "work", projectCode: "unknown" }).projectId, undefined);
});
