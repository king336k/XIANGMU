import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const walk = (node) =>
  !node || typeof node !== "object"
    ? []
    : Array.isArray(node)
      ? node.flatMap(walk)
      : [node, ...walk(node.props?.children)];
function load(name, mocks) {
  const exports = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(`../core/components/quality/${name}.tsx`, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )(
    (id) => mocks[id] || (id === "react/jsx-runtime" ? require(id) : new Proxy({}, { get: () => () => null })),
    exports
  );
  return exports;
}
function detail(tab, writable = false) {
  let index = 0;
  const closed = [];
  const api = load("defect-detail", {
    react: { ...React, useState: (value) => [index++ === 2 ? tab : value, () => {}] },
    "./shared": { Modal: "Modal", Badge: "Badge" },
    "./types": { can: () => writable, severityNames: { major: "严重" } },
    "./defect-disposition": { resolutionNames: {} },
  });
  const tree = api.DefectDetail({
    base: "/q/",
    value: { id: "d", code: "Q-D-1", title: "数据异常", status: "resolved", severity: "major", collaborators: [] },
    context: { members: [], is_manager: writable, project_name: "平台基础知识" },
    projectUrl: "/p",
    onClose: () => closed.push(true),
    onEdit() {},
    onChanged: async () => {},
  });
  return { tree, closed };
}
test("缺陷详情使用整页视觉，回归区占满卡片且没有右属性栏或重复工具区", () => {
  const { tree } = detail("regression");
  const nodes = walk(tree),
    modal = nodes.find((node) => node.type === "Modal");
  assert.equal(modal.props.presentation, "page");
  assert.ok(!nodes.some((node) => node.type === "aside"));
  assert.ok(!nodes.some((node) => node.props?.["aria-label"] === "缺陷来源与创建信息"));
  assert.ok(!nodes.some((node) => node.props?.children === "更多处理"));
  assert.ok(nodes.some((node) => node.props?.["aria-label"] === "缺陷详情内容"));
  assert.ok(!nodes.some((node) => node.props?.children === "编辑缺陷"));
});
test("非回归页保留属性和授权后的编辑功能，只读账号没有保存入口", () => {
  const nodes = walk(detail("overview", true).tree);
  assert.ok(nodes.some((node) => node.type === "aside"));
  assert.ok(nodes.some((node) => node.props?.["aria-label"] === "编辑影响版本"));
  assert.ok(!walk(detail("overview").tree).some((node) => node.props?.["aria-label"] === "编辑影响版本"));
});
test("page dialog保留native top layer和返回/ESC关闭，普通modal保留关闭页脚", () => {
  globalThis.document = { body: {} };
  let shows = 0,
    closed = 0;
  const api = load("shared", {
    react: {
      ...React,
      useState: (value) => [value, () => {}],
      useRef: () => ({
        current: {
          showModal() {
            shows++;
          },
        },
      }),
      useId: () => "title",
      useEffect: (effect) => effect(),
    },
    "react-dom": { createPortal: (node) => node },
    "@plane/ui": { Button: "Button" },
    "./pagination": {},
  });
  const page = api.Modal({
    title: "缺陷",
    presentation: "page",
    onClose() {
      closed++;
    },
    children: "body",
  });
  assert.equal(page.type, "dialog");
  assert.match(page.props.className, /defect-page/);
  assert.equal(shows, 1);
  walk(page)
    .find((node) => node.type === "button" && node.props.children?.includes?.("返回缺陷列表"))
    .props.onClick();
  page.props.onCancel({ target: page, currentTarget: page, preventDefault() {} });
  assert.equal(closed, 2);
  assert.ok(!walk(page).some((node) => node.type === "Button" && node.props.children === "关闭"));
  const ordinary = api.Modal({ title: "编辑", onClose() {}, children: "form" });
  assert.ok(!ordinary.props.className.includes("defect-page"));
  assert.ok(walk(ordinary).some((node) => node.type === "Button" && node.props.children === "关闭"));
});

test("缺陷整页顶部仅返回列表，宽度随窗口展开", () => {
  globalThis.document = { body: {} };
  const api = load("shared", {
    react: {
      ...React,
      useState: (value) => [value, () => {}],
      useRef: () => ({ current: { showModal() {} } }),
      useId: () => "title",
      useEffect: (fn) => fn(),
    },
    "react-dom": { createPortal: (node) => node },
    "@plane/ui": { Button: "Button" },
    "./pagination": {},
  });
  const tree = api.Modal({
    title: "缺陷",
    presentation: "page",
    breadcrumb: "遥操DAQ联调测试",
    onClose() {},
    children: "body",
  });
  assert.ok(!walk(tree).some((n) => n.props?.className === "defect-page-topbar"));
  assert.ok(walk(tree).some((n) => n.type === "button" && n.props.children?.includes?.("返回缺陷列表")));
  const css = readFileSync(new URL("../styles/globals.css", import.meta.url), "utf8");
  assert.doesNotMatch(css, /\.defect-page-card\s*\{[^}]*max-width:\s*1152px/);
});
