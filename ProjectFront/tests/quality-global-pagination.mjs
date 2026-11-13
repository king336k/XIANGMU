import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const Paging = () => null;
function load(file, mocks = {}) {
  const exports = {};
  const code = ts.transpileModule(readFileSync(new URL(`../core/components/${file}`, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  new Function("require", "exports", code)(
    (id) => mocks[id] ?? (id === "react/jsx-runtime" ? require(id) : new Proxy({}, { get: () => () => null })),
    exports
  );
  return exports;
}
function harness() {
  const values = [],
    queries = [];
  let cursor = 0;
  const hooks = {
    ...React,
    useState(initial) {
      const i = cursor++;
      if (!(i in values)) values[i] = initial;
      return [
        values[i],
        (next) => {
          values[i] = typeof next === "function" ? next(values[i]) : next;
        },
      ];
    },
    useEffect() {},
    useRef: (initial) => ({ current: initial }),
  };
  const reset = () => {
    cursor = 0;
    queries.length = 0;
  };
  const { useCollectionPagination } = load("quality/use-collection-pagination.tsx", { react: hooks });
  return { hooks, reset, values, queries, useCollectionPagination };
}
function nodes(tree) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
test("完整数组分页覆盖101条且改变每页数量返回首页，不改原数组", () => {
  const h = harness(),
    rows = Array.from({ length: 101 }, (_, id) => ({ id }));
  let state = h.useCollectionPagination("scope", rows);
  state.paging.onChange(3);
  h.reset();
  state = h.useCollectionPagination("scope", rows);
  assert.deepEqual(
    state.rows.map((row) => row.id),
    [100]
  );
  state.paging.onPageSizeChange(20);
  h.reset();
  state = h.useCollectionPagination("scope", rows);
  assert.equal(state.page, 1);
  assert.equal(state.rows.length, 20);
  assert.equal(rows.length, 101);
});
test("技术方案与现场工作站读取后端页码和条数，翻页不局限首50条", () => {
  for (const [file, name, endpoint] of [
    ["solution-panel", "SolutionPanel", "solutions/"],
    ["field-resources-panel", "FieldResourcesPanel", "field-agents/"],
  ]) {
    const h = harness();
    const exports = load(`quality/${file}.tsx`, {
      react: h.hooks,
      swr: {
        default: (query) => {
          h.queries.push(query);
          return { data: { results: [], count: 101 }, mutate() {} };
        },
      },
      "./use-collection-pagination": { useCollectionPagination: h.useCollectionPagination },
      "./shared": { Paging, Field: "field", Modal: "modal" },
      "./types": { can: () => false },
      "@plane/ui": { Button: "button" },
    });
    let tree = exports[name]({ base: "/quality/", defectId: "defect", context: { is_manager: false, members: [] } });
    let paging = nodes(tree).find((node) => node.type === Paging);
    assert.ok(paging, `${file}必须有分页`);
    assert.equal(paging.props.count, 101);
    paging.props.onChange(2);
    h.reset();
    tree = exports[name]({ base: "/quality/", defectId: "defect", context: { is_manager: false, members: [] } });
    assert.ok(
      h.queries.some((query) => query.includes(endpoint) && query.includes("page=2") && query.includes("per_page=50"))
    );
    paging = nodes(tree).find((node) => node.type === Paging);
    paging.props.onPageSizeChange(100);
    h.reset();
    exports[name]({ base: "/quality/", defectId: "defect", context: { is_manager: false, members: [] } });
    assert.ok(h.queries.some((query) => query.includes("page=1") && query.includes("per_page=100")));
  }
});
test("诊断分页查询保持缺陷范围且修改条数回到第一页", () => {
  const h = harness();
  const { DiagnosticsPanel } = load("quality/diagnostics-panel.tsx", {
    react: h.hooks,
    swr: {
      default: (query) => {
        h.queries.push(query);
        return { data: { results: [], count: 101 }, mutate() {} };
      },
    },
    "./use-collection-pagination": { useCollectionPagination: h.useCollectionPagination },
    "./shared": { Paging },
    "./types": { can: () => false },
  });
  let tree = DiagnosticsPanel({ base: "/quality/", defectId: "defect-a", context: {} });
  const paging = nodes(tree).find((node) => node.type === Paging);
  paging.props.onChange(3);
  h.reset();
  tree = DiagnosticsPanel({ base: "/quality/", defectId: "defect-a", context: {} });
  assert.ok(h.queries.some((query) => query.includes("defects/defect-a/diagnostics/?page=3&per_page=50")));
  h.reset();
  DiagnosticsPanel({ base: "/quality/", defectId: "defect-b", context: {} });
  assert.ok(h.queries.some((query) => query.includes("defects/defect-b/diagnostics/?page=1&per_page=50")));
});
test("服务端选择器翻页搜索保留已选，不以首100条作为候选全集", () => {
  const h = harness();
  let response = { results: [{ id: "chosen", title: "保留方案" }], count: 101 };
  const { PagedRecordSelect } = load("quality/paged-record-select.tsx", {
    react: h.hooks,
    swr: {
      default: (query) => {
        h.queries.push(query);
        return { data: response };
      },
    },
    "./use-collection-pagination": { useCollectionPagination: h.useCollectionPagination },
    "./shared": { Paging },
  });
  const render = () =>
    PagedRecordSelect({
      url: "/solutions/?defect_id=d&status=approved",
      name: "solution_id",
      placeholder: "选择方案",
      getLabel: (row) => row.title,
    });
  let tree = render();
  nodes(tree)
    .find((node) => node.type === "select")
    .props.onChange({ target: { value: "chosen" } });
  nodes(tree)
    .find((node) => node.type === Paging)
    .props.onChange(2);
  response = { results: [{ id: "other", title: "其他方案" }], count: 101 };
  h.reset();
  tree = render();
  assert.ok(h.queries[0].includes("page=2&per_page=50"));
  const select = nodes(tree).find((node) => node.type === "select");
  assert.equal(select.props.value, "chosen");
  assert.ok(nodes(select).some((node) => node.type === "option" && node.props.value === "chosen"));
  nodes(tree)
    .find((node) => node.type === "input")
    .props.onChange({ target: { value: "中文" } });
  h.reset();
  tree = render();
  const query = new URL(h.queries[0], "https://example.test").searchParams;
  assert.equal(query.get("page"), "1");
  assert.equal(query.get("search"), "中文");
  assert.equal(query.get("defect_id"), "d");
  assert.equal(nodes(tree).find((node) => node.type === "select").props.value, "chosen");
});
test("用例选择器25/50/100同时调整已选列表与服务端页，仍保留500选择上限", () => {
  const h = harness();
  const selected = Array.from({ length: 101 }, (_, id) => ({
    id: String(id),
    title: `case${id}`,
    module: "",
    priority: "P1",
    version: 1,
  }));
  const Field = "field",
    Button = "button";
  const { CasePicker } = load("quality/case-picker.tsx", {
    react: h.hooks,
    swr: {
      default: (query) => {
        h.queries.push(query);
        return { data: { results: selected.slice(0, 25), count: 101, modules: [] } };
      },
    },
    "./shared": { Paging, Field },
    "./types": { priorityNames: {} },
    "@plane/ui": { Button },
    "./case-selection": { mergeCaseSelection: (_, rows) => rows },
  });
  const render = () => CasePicker({ base: "/quality/", selected, onChange() {} });
  let tree = render();
  nodes(tree)
    .find((node) => node.type === "input" && typeof node.props.checked === "boolean" && !node.props["aria-label"])
    .props.onChange({ target: { checked: true } });
  h.reset();
  tree = render();
  let paging = nodes(tree).find((node) => node.type === Paging);
  assert.deepEqual(paging.props.pageSizes, [25, 50, 100]);
  paging.props.onPageSizeChange(50);
  h.reset();
  tree = render();
  paging = nodes(tree).find((node) => node.type === Paging);
  paging.props.onChange(3);
  h.reset();
  tree = render();
  assert.equal(nodes(tree).filter((node) => node.type === "tr").length, 2, "最后一页剩一个已选用例和表头");
  assert.ok(h.queries[0].includes("per_page=50") && h.queries[0].includes("page=3"));
  const { mergeCaseSelection } = load("quality/case-selection.ts");
  assert.throws(
    () =>
      mergeCaseSelection(
        Array.from({ length: 500 }, (_, id) => ({ id: String(id) })),
        [{ id: "new" }],
        true
      ),
    /500/
  );
});
test("账号管理的平台总数独立于外部目录，搜索和条数切换维持服务端分页", () => {
  const h = harness();
  const { AccountManager } = load("quality/account-manager.tsx", {
    react: h.hooks,
    swr: {
      default: (query) => {
        h.queries.push(query);
        return {
          data: {
            can_manage: true,
            count: 101,
            results: [],
            external_results: [
              { source_instance: "remote", external_user_id: 1, username: "外部用户", source: "remote" },
            ],
            external_partial: true,
          },
          mutate() {},
        };
      },
    },
    "./use-collection-pagination": { useCollectionPagination: h.useCollectionPagination },
    "./shared": { Paging, Field: "field", Modal: "modal" },
    "@plane/ui": { Button: "button" },
  });
  const render = () => AccountManager({ project: { workspace: "demo", id: "project" } });
  let tree = render(),
    paging = nodes(tree).find((node) => node.type === Paging);
  assert.equal(paging.props.count, 101, "不能把外部目录数量加进平台分页总数");
  paging.props.onChange(3);
  h.reset();
  tree = render();
  assert.equal(new URL(h.queries[0], "https://example.test").searchParams.get("page"), "3");
  nodes(tree)
    .find((node) => node.type === "input" && node.props.value === "")
    .props.onChange({ target: { value: "账号" } });
  h.reset();
  tree = render();
  const query = new URL(h.queries[0], "https://example.test").searchParams;
  assert.equal(query.get("page"), "1");
  assert.equal(query.get("search"), "账号");
  assert.equal(query.get("project_id"), "project");
  paging = nodes(tree).find((node) => node.type === Paging);
  paging.props.onPageSizeChange(20);
  h.reset();
  render();
  assert.equal(new URL(h.queries[0], "https://example.test").searchParams.get("per_page"), "20");
});
test("版本关联记录选择器请求真实per_page，搜索重置页码", () => {
  const h = harness();
  const { VersionRecordPicker } = load("quality/version-forms.tsx", {
    react: h.hooks,
    swr: {
      default: (query) => {
        h.queries.push(query);
        return { data: { results: [], count: 101 } };
      },
    },
    "./use-collection-pagination": { useCollectionPagination: h.useCollectionPagination },
    "./shared": { Paging },
  });
  const render = () => VersionRecordPicker({ base: "/quality/", kind: "issue", value: "", onChange() {} });
  let tree = render();
  let paging = nodes(tree).find((node) => node.type === Paging);
  assert.equal(paging.props.perPage, 25);
  paging.props.onPageSizeChange(100);
  h.reset();
  tree = render();
  let query = new URL(h.queries[0], "https://example.test").searchParams;
  assert.equal(query.get("per_page"), "100");
  paging = nodes(tree).find((node) => node.type === Paging);
  paging.props.onChange(2);
  h.reset();
  tree = render();
  nodes(tree)
    .find((node) => node.type === "input")
    .props.onChange({ target: { value: "中文" } });
  h.reset();
  render();
  query = new URL(h.queries[0], "https://example.test").searchParams;
  assert.equal(query.get("page"), "1");
  assert.equal(query.get("search"), "中文");
  assert.equal(query.get("kind"), "issue");
});
