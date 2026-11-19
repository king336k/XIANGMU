import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const f = () => Promise.resolve();
function requests(page) {
  const keys = [],
    exp = {};
  const source = ts.transpileModule(
    readFileSync(new URL("../core/layouts/auth-layout/project-wrapper.tsx", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }
  ).outputText;
  new Function("require", "exports", source)((id) => {
    if (id === "react/jsx-runtime") return require(id);
    if (id === "react") return { ...React, useState: (v) => [v, () => {}], useEffect() {} };
    if (id === "react-router")
      return { useLocation: () => ({ pathname: "/w/p/BASEKNOW/" + page + "/" }), useParams: () => ({}) };
    if (id === "mobx-react") return { observer: (v) => v };
    if (id === "swr")
      return {
        default: (key) => {
          if (key) keys.push(key);
          return { isLoading: false };
        },
      };
    if (id === "@plane/constants")
      return new Proxy(
        {
          EUserPermissions: { ADMIN: 20, MEMBER: 15, GUEST: 5 },
          EUserPermissionsLevel: { PROJECT: "project", WORKSPACE: "workspace" },
        },
        { get: (o, k) => o[k] || ((...args) => [k, ...args].join(":")) }
      );
    if (id === "@plane/types") return { GANTT_TIMELINE_TYPE: { MODULE: "module" } };
    if (id.endsWith("/user"))
      return {
        useUser: () => ({ data: { id: "actor" } }),
        useUserPermissions: () => ({
          allowPermissions: () => true,
          getProjectRoleByWorkspaceSlugAndProjectId: () => 20,
          fetchUserProjectInfo: f,
          joinProject: f,
        }),
      };
    if (id === "@/hooks/store/use-member")
      return { useMember: () => ({ project: { fetchProjectMembers: f, fetchProjectUserProperties: f } }) };
    return new Proxy(
      {},
      { get: () => () => new Proxy({ setWritePermissions: f, initGantt: f }, { get: (o, k) => o[k] || f }) }
    );
  }, exp);
  exp.ProjectAuthWrapper({ workspaceSlug: "w", projectId: "p", children: null });
  return keys;
}
test("原生业务页不预取任务页的周期、模块、视图、估点和收件箱", () => {
  for (const route of ["defects", "requirements", "quality", "versions", "pages", "knowledge"]) {
    const keys = requests(route);
    for (const key of [
      "PROJECT_ALL_CYCLES",
      "PROJECT_MODULES",
      "PROJECT_VIEWS",
      "PROJECT_ESTIMATES",
      "PROJECT_INTAKE_STATE",
    ])
      assert.ok(!keys.some((k) => String(k).startsWith(key)), route + ":" + key);
    assert.ok(keys.some((k) => String(k).startsWith("PROJECT_DETAILS")));
    assert.ok(keys.some((k) => String(k).startsWith("PROJECT_ME_INFORMATION")));
  }
});
test("任务页面仍读取完整的任务选项", () => {
  const keys = requests("issues");
  for (const key of [
    "PROJECT_ALL_CYCLES",
    "PROJECT_MODULES",
    "PROJECT_VIEWS",
    "PROJECT_ESTIMATES",
    "PROJECT_INTAKE_STATE",
  ])
    assert.ok(
      keys.some((k) => String(k).startsWith(key)),
      key
    );
});
