import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const nodes = (tree) =>
  !tree || typeof tree !== "object"
    ? []
    : Array.isArray(tree)
      ? tree.flatMap(nodes)
      : [tree, ...nodes(tree.props?.children)];
function load(name, mocks) {
  const exp = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(`../core/components/quality/${name}.tsx`, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((id) => mocks[id] || (id === "react/jsx-runtime" ? require(id) : new Proxy({}, { get: () => () => null })), exp);
  return exp;
}
test("保存方案后刷新父缺陷版本及匹配的全部进度分页缓存", async () => {
  const states = [],
    events = [],
    refreshed = [];
  let index = 0;
  const keys = [
    "/q/record-progress/?page=1&kind=defect&id=d",
    "/q/record-progress/?page=2&kind=defect&id=d",
    "/q/record-progress/?kind=defect&id=other",
    "/q/record-progress/?kind=plan&id=d",
    "/else/record-progress/?kind=defect&id=d",
  ];
  const exp = load("solution-panel", {
    react: {
      useState: (value) => {
        const at = index++;
        if (!(at in states)) states[at] = value;
        return [
          states[at],
          (next) => {
            states[at] = next;
          },
        ];
      },
    },
    swr: {
      default: () => ({
        data: { results: [], count: 0, can_create: true },
        mutate: async () => events.push("solutions"),
      }),
      useSWRConfig: () => ({ mutate: async (filter) => refreshed.push(...keys.filter(filter)) }),
    },
    "./api": {
      qualityApi: {
        write: async () => {
          events.push("write");
          return { id: "s" };
        },
      },
    },
    "./shared": { Modal: "Modal", Field: "Field", Paging: "Paging" },
    "./use-collection-pagination": { useCollectionPagination: () => ({ query: "page=1", paging: {} }) },
    "./solution-data": { solutionFields: [], currentSolutionRevision: () => null },
    "@plane/ui": { Button: "Button" },
  });
  const render = () => {
    index = 0;
    return exp.SolutionPanel({
      base: "/q/",
      defectId: "d",
      context: { members: [] },
      onChanged: async () => events.push("defect"),
    });
  };
  nodes(render())
    .find((n) => n.type === "Button" && n.props.children === "新增方案")
    .props.onClick();
  await nodes(render())
    .find((n) => n.type === "Modal")
    .props.onSubmit(new FormData());
  assert.deepEqual(events, ["write", "solutions", "defect"]);
  assert.deepEqual(refreshed, keys.slice(0, 2));
});
test("父详情收到方案变更读取新缺陷，传播真实版本而非复用旧对象", async () => {
  let index = 0;
  const changes = [],
    reads = [];
  const fresh = { id: "d", status: "in_progress", edit_version: 2 };
  const exp = load("defect-detail", {
    react: { useState: (v) => [index++ === 3 ? "solution" : v, () => {}] },
    "./solution-panel": { SolutionPanel: "SolutionPanel" },
    "./shared": { Badge: "Badge", Modal: "Modal" },
    "./types": { can: () => true, severityNames: {} },
    "./defect-disposition": { resolutionNames: {}, DefectDispositionPanel: "DefectDispositionPanel" },
    "./api": {
      qualityApi: {
        read: async (url) => {
          reads.push(url);
          return fresh;
        },
      },
    },
  });
  const tree = exp.DefectDetail({
    base: "/q/",
    value: { id: "d", title: "真实缺陷", status: "open", edit_version: 1, collaborators: [] },
    context: { members: [] },
    projectUrl: "/p",
    onChanged: async (v) => changes.push(v),
    onEdit() {},
    onClose() {},
  });
  const panel = nodes(tree).find((n) => n.type === "SolutionPanel");
  assert.ok(panel);
  await panel.props.onChanged();
  assert.deepEqual(reads, ["/q/defects/d/"]);
  assert.deepEqual(changes, [fresh]);
});
