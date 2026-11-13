import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
function load(name, mocks = {}) {
  const e = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(`../core/components/quality/${name}`, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )(
    (id) =>
      mocks[id] ||
      (id === "react/jsx-runtime" || id === "react" ? require(id) : new Proxy({}, { get: () => () => null })),
    e
  );
  return e;
}
const helper = load("solution-data.ts");
const Badge = ({ value, label }) => React.createElement("span", { "data-tone": value }, label);
const shared = { "./shared": { Badge }, "@plane/utils": { renderNumericDateTime: String } };
const content = load("solution-content.tsx", { "./solution-data": helper, ...shared });
const { SolutionCard } = load("solution-card.tsx", {
  "./solution-data": helper,
  "./solution-content": content,
  ...shared,
  "@plane/ui": { Button: ({ children, ...p }) => React.createElement("button", p, children) },
});
const solution = {
  id: "s",
  title: "录制状态修复",
  status: "approved",
  edit_version: 3,
  submitted_version: 1,
  created_by_id: "tech",
  created_by_name: "技术员",
  root_cause: "状态未复位",
  steps: "停止后更新状态",
  verification: "重复启停验证",
  risk: "",
  rollback: "",
  repository: "",
  commit_sha: "",
  can_edit: true,
  can_submit: false,
  can_review: false,
  current_revision_id: "r",
  revisions: [
    {
      id: "r",
      version: 1,
      snapshot: {},
      reviewer_ids: ["manager"],
      required_count: 1,
      reviews: [
        {
          id: "vote",
          created_by_id: "manager",
          actor: "项目经理",
          decision: "approve",
          comment: "修复方案确认",
          created_at: "2026-11-12T10:00:00Z",
        },
      ],
    },
  ],
};
test("方案正文分段可见，仅展示真实送审版本，审核意见直接显示且历史折叠", () => {
  const html = renderToStaticMarkup(
    React.createElement(SolutionCard, {
      solution,
      context: { user_id: "tech", members: [] },
      onEdit() {},
      onSubmit() {},
      onReview() {},
      onSnapshot() {},
    })
  );
  for (const text of [
    "根因分析",
    "状态未复位",
    "解决步骤",
    "停止后更新状态",
    "验证方法",
    "重复启停验证",
    "v1",
    "项目经理",
    "修复方案确认",
    "已通过 1/1 人",
    "修改并重新送审",
  ])
    assert.ok(html.includes(text), text);
  assert.doesNotMatch(html, /修订3/);
  assert.match(html, /<details[^>]*>[\s\S]*审核记录与历史版本/);
  assert.doesNotMatch(html, /<details[^>]*open/);
});
test("创建人操作仍受服务端状态限制，审核中方案没有编辑送审和审核按钮", () => {
  const html = renderToStaticMarkup(
    React.createElement(SolutionCard, {
      solution: { ...solution, status: "review", can_edit: false, can_submit: false, can_review: false },
      context: { user_id: "tech", members: [] },
      onEdit() {},
      onSubmit() {},
      onReview() {},
      onSnapshot() {},
    })
  );
  assert.doesNotMatch(html, /编辑方案|修改并重新送审|>提交审核<|>审核方案</);
});
