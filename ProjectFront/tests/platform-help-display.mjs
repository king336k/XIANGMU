import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const walk = (node) =>
  !node || typeof node !== "object"
    ? []
    : Array.isArray(node)
      ? node.flatMap(walk)
      : [node, ...walk(node.props?.children)];
const text = (node) =>
  node == null || typeof node === "boolean"
    ? ""
    : typeof node === "string" || typeof node === "number"
      ? String(node)
      : Array.isArray(node)
        ? node.map(text).join("")
        : text(node.props?.children);
function load(path, mocks = {}) {
  const exports = {};
  const source = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  new Function("require", "exports", source)(
    (id) => mocks[id] || (id === "react/jsx-runtime" ? require(id) : new Proxy({}, { get: () => () => null })),
    exports
  );
  return exports;
}
const guide = load("../core/components/workspace/sidebar/help-section/platform-guide.ts");
const paths = load("../core/components/settings/management-paths.ts");
function harness() {
  const states = [];
  let index = 0;
  const api = load("../core/components/workspace/sidebar/help-section/platform-help.tsx", {
    react: {
      useRef: () => ({ current: null }),
      useEffect: () => {},
      useState(value) {
        const at = index++;
        if (!(at in states)) states[at] = value;
        return [states[at], (v) => (states[at] = v)];
      },
    },
    "./platform-guide": guide,
    "@/components/settings/management-paths": paths,
    "@/hooks/use-resolved-project-params": {
      useResolvedProjectParams: () => ({ workspaceSlug: "work", projectId: "project" }),
    },
    "@/components/quality/shared": { Modal: "Modal", fieldClass: "field" },
    "@/components/common/project-route-link": { ProjectRouteLink: "Link" },
    "./guide-screenshots": { GuideScreenshots: "Diagrams" },
  });
  return {
    api,
    render() {
      index = 0;
      return api.PlatformHelp({ onClose() {} });
    },
  };
}
test("公共与角色目录可筛选，搜索无匹配有说明，继续阅读可跨组恢复目录", () => {
  const h = harness();
  let tree = h.render();
  const button = (label) => walk(tree).find((n) => n.type === "button" && text(n).startsWith(label));
  assert.ok(walk(tree).some((n) => n.props?.["aria-label"] === "开始使用与功能地图"));
  button("角色指南").props.onClick();
  tree = h.render();
  assert.ok(walk(tree).some((n) => n.props?.["aria-label"] === "管理员操作指南"));
  button("技术员操作指南").props.onClick();
  tree = h.render();
  assert.ok(walk(tree).some((n) => n.props?.["aria-label"] === "技术员操作指南"));
  assert.equal(walk(tree).filter((n) => n.type === "Diagrams").length, 1);
  button("缺陷完整闭环").props.onClick();
  tree = h.render();
  assert.ok(walk(tree).some((n) => n.props?.["aria-label"] === "缺陷完整闭环"));
  walk(tree)
    .find((n) => n.type === "input")
    .props.onChange({ target: { value: "不存在XYZ" } });
  tree = h.render();
  assert.match(text(tree), /未找到相关内容/);
});
test("帮助快捷链接使用当前项目，并使用已迁移的设置入口", () => {
  const { api } = harness();
  assert.equal(api.guideLinkPath("work", "project", "/quality?tab=roles"), "/work/settings/members/?project=project");
  assert.equal(
    api.guideLinkPath("work", "project", "/knowledge?tab=settings"),
    "/work/settings/models/?project=project"
  );
  assert.equal(api.guideLinkPath("work", "project", "/defects?create=1"), "/work/projects/project/defects?create=1");
  assert.equal(
    api.guideLinkPath("work", "project", "/settings/connections/"),
    "/work/settings/connections/?project=project"
  );
  assert.equal(
    api.guideLinkPath("work", "project", "/settings/daq-projects/"),
    "/work/settings/daq-projects/?project=project"
  );
});
test("真实截图使用资源自身比例，放大与关闭不丢图注", () => {
  let expanded;
  const { GuideScreenshots } = load("../core/components/workspace/sidebar/help-section/guide-screenshots.tsx", {
    react: { useState: () => [expanded, (v) => (expanded = v)] },
    "@/components/quality/shared": { Modal: "Modal" },
  });
  const image = {
    src: "/platform-guide/solution-real.webp",
    title: "修复方案实际截图",
    caption: "检查方案与修复交接",
    width: 1200,
    height: 650,
  };
  let tree = GuideScreenshots({ images: [image] });
  assert.equal(walk(tree).find((n) => n.type === "img").props.height, 650);
  walk(tree)
    .find((n) => n.type === "button")
    .props.onClick();
  tree = GuideScreenshots({ images: [image] });
  const modal = walk(tree).find((n) => n.type === "Modal");
  assert.ok(modal);
  assert.match(text(modal), /检查方案与修复交接/);
  modal.props.onClose();
  assert.equal(walk(GuideScreenshots({ images: [image] })).filter((n) => n.type === "Modal").length, 0);
});
