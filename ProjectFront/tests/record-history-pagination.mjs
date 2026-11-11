import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
function load(name, mocks) {
  const exports = {};
  const code = ts.transpileModule(
    readFileSync(new URL(`../core/components/quality/${name}`, import.meta.url), "utf8"),
    {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }
  ).outputText;
  new Function("require", "exports", code)(
    (id) => mocks[id] ?? (id === "react/jsx-runtime" ? require(id) : new Proxy({}, { get: () => () => null })),
    exports
  );
  return exports;
}
function visit(node, type) {
  if (!node || typeof node !== "object") return;
  if (Array.isArray(node)) return node.map((item) => visit(item, type)).find(Boolean);
  if (node.type === type) return node;
  return visit(node.props?.children, type);
}
const Paging = () => null;
const Icon = () => null;
const Menu = () => null;
Menu.MenuItem = Icon;
function setup(file, name, initialMode) {
  let cursor = 0;
  const state = [],
    requested = [];
  const react = {
    ...React,
    useEffect() {},
    useState(initial) {
      const index = cursor++;
      if (!(index in state)) state[index] = index === 0 ? initialMode : initial;
      return [
        state[index],
        (next) => {
          state[index] = typeof next === "function" ? next(state[index]) : next;
        },
      ];
    },
  };
  const { useCollectionPagination } = load("use-collection-pagination.tsx", { react });
  const api = { read() {} };
  const mocks = {
    react,
    "@plane/ui": { CustomMenu: Menu },
    "lucide-react": new Proxy({}, { get: () => Icon }),
    "./use-collection-pagination": { useCollectionPagination },
    "./shared": { Paging },
    "./api": { qualityApi: api, errorMessage: String },
    swr: {
      default(key) {
        if (!key) return {};
        const url = Array.isArray(key) ? key[0] : key;
        requested.push(url);
        const query = new URL(url, "http://test").searchParams,
          page = Number(query.get("page"));
        return {
          data: {
            events: [
              {
                id: `event-${page}`,
                note: `note-${page}`,
                actor: "actor",
                label: "处理",
                date: "2026-11-09",
                created_at: "2026-11-09",
                status: "planning",
              },
            ],
            event_pagination: { count: 201, page, per_page: 50 },
            dates: [],
            stages: [],
            schedule: [],
            versions: [],
          },
        };
      },
    },
    "@plane/utils": { renderNumericDateTime: String },
    "./version-types": { versionStatuses: { planning: "规划中" } },
  };
  const C = load(file, mocks)[name];
  return {
    requested,
    render(props) {
      cursor = 0;
      return C(props);
    },
    paging(tree) {
      return visit(tree, Paging).props;
    },
  };
}

test("记录历程翻页请求真正服务端页，显示完整计数，切换kind或record回到首页", () => {
  const s = setup("record-progress.tsx", "RecordProgress", "timeline");
  const props = { base: "/api/quality/", kind: "defect", id: "one", projectUrl: "/p" };
  let tree = s.render(props);
  assert.equal(s.paging(tree).count, 201);
  s.paging(tree).onChange(3);
  tree = s.render(props);
  assert.match(s.requested.at(-1), /page=3/);
  assert.match(JSON.stringify(tree), /note-3/);
  s.render({ ...props, id: "two" });
  assert.match(s.requested.at(-1), /page=1/);
  assert.match(s.requested.at(-1), /id=two/);
  s.paging(tree).onPageSizeChange(100);
  s.render(props);
  assert.match(s.requested.at(-1), /page=1&per_page=100/);
});

test("版本历史独立翻页，count不取已加载行数，切换版本及项目回到第一页", () => {
  const s = setup("version-event-history.tsx", "VersionEventHistory", true);
  const props = { base: "/one/", version: { id: "v1", edit_version: 1, event_pagination: { count: 201 } } };
  let tree = s.render(props);
  assert.equal(s.paging(tree).count, 201);
  s.paging(tree).onChange(2);
  tree = s.render(props);
  assert.match(s.requested.at(-1), /versions\/v1\/\?page=2/);
  assert.match(JSON.stringify(tree), /note-2/);
  s.render({ ...props, version: { ...props.version, id: "v2" } });
  assert.match(s.requested.at(-1), /versions\/v2\/\?page=1/);
  s.render({ ...props, base: "/other/" });
  assert.match(s.requested.at(-1), /other\/versions\/v1\/\?page=1/);
});
