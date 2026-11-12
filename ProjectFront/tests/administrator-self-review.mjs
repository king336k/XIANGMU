import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
const stubs = new Map();
const stub = (n) => {
  if (!stubs.has(n)) stubs.set(n, () => null);
  return stubs.get(n);
};
const revision = { id: "r1", version: 2, reviewer_ids: ["actor"], snapshot: {}, reviews: [], required_count: 1 };
const solution = {
  id: "s",
  title: "自己的方案",
  created_by_id: "actor",
  contributor_ids: ["actor"],
  status: "draft",
  edit_version: 3,
  revisions: [revision],
  current_revision_id: "r1",
  current_revision_version: 2,
  can_edit: true,
  can_submit: true,
  can_review: true,
  root_cause: "已记录根因",
};
function harness(is_administrator, status = "draft") {
  let cursor = 0;
  const state = [],
    writes = [],
    exp = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/quality/solution-panel.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }
    ).outputText
  )((id) => {
    if (id === "react")
      return {
        ...React,
        useState(initial) {
          const at = cursor++;
          if (!(at in state)) state[at] = initial;
          return [
            state[at],
            (v) => {
              state[at] = v;
            },
          ];
        },
      };
    if (id === "react/jsx-runtime") return require(id);
    if (id === "swr")
      return {
        default: () => ({
          data: {
            results: [
              {
                ...solution,
                status,
                can_edit: status !== "review",
                can_submit: status === "draft",
                can_review: status === "review" && is_administrator,
              },
            ],
            count: 1,
            can_create: true,
          },
          mutate: async () => {},
        }),
      };
    if (id === "./use-collection-pagination")
      return { useCollectionPagination: () => ({ query: "page=1", paging: {} }) };
    if (id === "./solution-data") {
      const helper = {};
      new Function(
        "exports",
        ts.transpileModule(
          readFileSync(new URL("../core/components/quality/solution-data.ts", import.meta.url), "utf8"),
          { compilerOptions: { module: ts.ModuleKind.CommonJS } }
        ).outputText
      )(helper);
      return helper;
    }
    if (id === "./solution-card")
      return {
        SolutionCard: (props) => {
          const b = [];
          if (props.solution.can_submit)
            b.push(require("react/jsx-runtime").jsx(stub("Button"), { children: "提交审核", onClick: props.onSubmit }));
          if (props.solution.can_review)
            b.push(require("react/jsx-runtime").jsx(stub("Button"), { children: "审核方案", onClick: props.onReview }));
          return require("react/jsx-runtime").jsx("div", { children: b });
        },
      };
    if (id === "./types") return { can: (c, key) => c.capabilities[key] === true };
    if (id === "./api") return { qualityApi: { write: async (...args) => writes.push(args) }, errorMessage: String };
    return new Proxy({}, { get: (_, key) => (key === "fieldClass" ? "field" : stub(key)) });
  }, exp);
  const context = {
    user_id: "actor",
    is_manager: true,
    is_administrator,
    business_roles_enabled: true,
    business_role: "PROJECT_MANAGER",
    capabilities: { solution: true, review: true },
    members: [
      {
        id: "actor",
        name: "本人",
        is_administrator,
        business_role: is_administrator ? "PLATFORM_ADMIN" : "PROJECT_MANAGER",
      },
    ],
  };
  return {
    writes,
    render() {
      cursor = 0;
      const tree = exp.SolutionPanel({ base: "/q/", defectId: "d", context });
      function expand(t) {
        if (!t || typeof t !== "object") return t;
        if (Array.isArray(t)) return t.map(expand);
        if (typeof t.type === "function" && t.props?.onSubmit && t.props?.solution) {
          return require("react/jsx-runtime").jsx("div", {
            children: [
              t.props.solution.can_submit
                ? require("react/jsx-runtime").jsx(stub("Button"), { children: "提交审核", onClick: t.props.onSubmit })
                : null,
              t.props.solution.can_review
                ? require("react/jsx-runtime").jsx(stub("Button"), { children: "审核方案", onClick: t.props.onReview })
                : null,
            ],
          });
        }
        return { ...t, props: { ...t.props, children: expand(t.props?.children) } };
      }
      return expand(tree);
    },
  };
}
const nodes = (t) =>
  !t || typeof t !== "object" ? [] : Array.isArray(t) ? t.flatMap(nodes) : [t, ...nodes(t.props?.children)];
const button = (t, label) => nodes(t).find((n) => n.type === stub("Button") && n.props.children === label);
test("权威管理员送审时可选本人，不需要第二管理员，普通作者仍不能选本人", () => {
  for (const admin of [true, false]) {
    const h = harness(admin);
    let tree = h.render();
    button(tree, "提交审核").props.onClick();
    tree = h.render();
    const input = nodes(tree).find(
      (n) => n.type === "input" && n.props.name === "reviewer_ids" && n.props.value === "actor"
    );
    assert.equal(!!input, admin);
  }
});
test("权威管理员能审核本人指定的当前方案版本，普通经理作者仍不显示自审", async () => {
  const h = harness(true, "review");
  let tree = h.render();
  assert.ok(button(tree, "审核方案"));
  button(tree, "审核方案").props.onClick();
  tree = h.render();
  await nodes(tree)
    .find((n) => n.type === stub("Modal"))
    .props.onSubmit(
      new Map([
        ["decision", "approve"],
        ["comment", "本人按材料核对通过"],
      ])
    );
  assert.deepEqual(h.writes, [
    ["/q/solutions/s/review/", { revision_id: "r1", decision: "approve", comment: "本人按材料核对通过" }],
  ]);
  assert.equal(button(harness(false, "review").render(), "审核方案"), undefined);
});

test("管理员送审仍保留版本号、显式审核人和通过人数，不改写真实actor", async () => {
  const h = harness(true);
  let tree = h.render();
  button(tree, "提交审核").props.onClick();
  tree = h.render();
  const form = {
    getAll: (key) => (key === "reviewer_ids" ? ["actor"] : []),
    get: (key) => (key === "required_count" ? "1" : null),
  };
  await nodes(tree)
    .find((n) => n.type === stub("Modal"))
    .props.onSubmit(form);
  assert.deepEqual(h.writes, [
    ["/q/solutions/s/submit/", { expected_version: 3, reviewer_ids: ["actor"], required_count: 1 }],
  ]);
});
