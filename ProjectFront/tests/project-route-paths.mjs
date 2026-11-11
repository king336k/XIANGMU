import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
function apiForPaths() {
  const result = {};
  new Function(
    "exports",
    ts.transpileModule(readFileSync(new URL("../helpers/project-route.ts", import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS },
    }).outputText
  )(result);
  return result;
}
const projects = [
  { id: "2c18bbf1-017c-4313-ba06-e208dcf4e163", identifier: "BOARD113", workspace: "w1" },
  { id: "other-id", identifier: "BOARD113", workspace: "w2" },
];
test("所有项目页面和设置使用项目编号短路径，保留查询和锚点，外站及接口不改", () => {
  const { shortProjectPath, internalProjectPath } = apiForPaths();
  for (const tail of [
    "issues/",
    "requirements/",
    "defects/",
    "quality/?tab=cases&per_page=50",
    "versions/?version=v1#flow",
    "cycles/c1/",
    "modules/m1/",
    "pages/page1/",
    "views/view1/",
    "archives/issues/",
  ]) {
    const old = `/work/projects/${projects[0].id}/${tail}`,
      short = `/work/p/BOARD113/${tail}`;
    assert.equal(shortProjectPath(old, projects, "w1"), short);
    assert.equal(internalProjectPath(short, projects, "w1"), old);
  }
  assert.equal(
    shortProjectPath(`/work/settings/projects/${projects[0].id}/members/`, projects, "w1"),
    "/work/p/BOARD113/settings/members/"
  );
  assert.equal(
    internalProjectPath("/work/p/BOARD113/settings/members/", projects, "w1"),
    `/work/settings/projects/${projects[0].id}/members/`
  );
  for (const url of [
    "https://external.invalid/work/projects/x/issues/",
    "/api/workspaces/work/projects/x/",
    "/work/projects/",
  ])
    assert.equal(shortProjectPath(url, projects, "w1"), url);
});
test("项目编号按工作空间解析；未知或同名有歧义不误指其他项目", () => {
  const { resolveProjectRouteParams } = apiForPaths();
  assert.equal(
    resolveProjectRouteParams({ workspaceSlug: "work", projectId: "board113" }, projects, "w1").projectId,
    projects[0].id
  );
  assert.equal(
    resolveProjectRouteParams({ workspaceSlug: "other", projectId: "board113" }, projects, "w2").projectId,
    "other-id"
  );
  assert.equal(
    resolveProjectRouteParams({ workspaceSlug: "work", projectId: "unknown" }, projects, "w1").projectId,
    undefined
  );
  assert.equal(
    resolveProjectRouteParams({ workspaceSlug: "work", projectId: projects[0].id }, projects, "w1").projectId,
    projects[0].id
  );
});
test("项目业务路由与设置路由统一使用p，旧UUID入口留作兼容跳转", () => {
  const routes = readFileSync(new URL("../app/routes/core.ts", import.meta.url), "utf8");
  assert.match(routes, /:workspaceSlug\/p\/:projectId\/issues/);
  assert.match(routes, /:workspaceSlug\/p\/:projectId\/settings\/members/);
  assert.match(routes, /projects\/:projectId\/\*/);
});

test("短路径已经使用项目编号时业务工作台不重复重定向", () => {
  for (const file of ["workbench.tsx", "requirements-workbench.tsx", "versions-workbench.tsx"]) {
    const code = readFileSync(new URL("../core/components/quality/" + file, import.meta.url), "utf8");
    assert.match(code, /canonicalParams.projectId.toLowerCase\(\) !== context.identifier.toLowerCase\(\)/);
  }
});

test("共用短链接保留路由对象、锚点、点击行为及看板拖动ref", () => {
  const React = require("react"),
    api = {},
    RouterLink = () => null,
    Control = () => null;
  const source = readFileSync(new URL("../core/components/common/project-route-link.tsx", import.meta.url), "utf8");
  const mocks = {
    react: React,
    "mobx-react": { observer: (fn) => fn },
    "react-router": { Link: RouterLink },
    "@plane/ui": { ControlLink: Control },
    "@/app/compat/next/navigation": {
      useProjectRoutePaths: () => ({ shortPath: (path) => apiRoute.shortProjectPath(path, projects, "w1") }),
    },
  };
  const apiRoute = apiForPaths();
  new Function(
    "require",
    "exports",
    ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } })
      .outputText
  )((id) => mocks[id] || require(id), api);
  const ref = { current: null },
    onClick = () => {};
  const old = `/work/projects/${projects[0].id}/issues/`,
    short = "/work/p/BOARD113/issues/";
  const link = api.ProjectRouteLink.render({ to: { pathname: old, search: "?page=2", hash: "#row" }, onClick }, ref);
  assert.deepEqual(link.props.to, { pathname: short, search: "?page=2", hash: "#row" });
  assert.equal(link.props.onClick, onClick);
  assert.equal(link.ref, ref);
  const control = api.ProjectControlLink.render({ href: old, onClick, children: "卡片", draggable: true }, ref);
  assert.equal(control.props.href, short);
  assert.equal(control.props.onClick, onClick);
  assert.equal(control.props.draggable, true);
  assert.equal(control.ref, ref);
});

test("项目根目录和旧项目设置前缀都有兼容落点", () => {
  const routes = readFileSync(new URL("../app/routes/core.ts", import.meta.url), "utf8");
  assert.match(routes, /route\(\s*":workspaceSlug\/p\/:projectId"/);
  assert.match(routes, /projects\/:projectId\/settings\/\*/);
});
