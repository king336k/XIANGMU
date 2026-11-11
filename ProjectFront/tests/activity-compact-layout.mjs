import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
const Comment = () => null,
  List = () => null;
function nodes(tree) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
function load(order, disabled) {
  const api = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/issues/issue-detail/issue-activity/root.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
    ).outputText
  )((id) => {
    if (id === "react") return { useMemo: (fn) => fn() };
    if (id === "react/jsx-runtime") return require(id);
    if (id === "mobx-react") return { observer: (fn) => fn };
    if (id === "@plane/constants") return { E_SORT_ORDER: { ASC: "asc", DESC: "desc" }, defaultActivityFilters: [] };
    if (id === "@plane/hooks")
      return {
        useLocalStorage: (key, initial) => ({
          storedValue: key === "activity_sort_order" ? order : initial,
          setValue() {},
        }),
      };
    if (id === "@plane/i18n") return { useTranslation: () => ({ t: () => "活动" }) };
    if (id === "@/hooks/store/use-project") return { useProject: () => ({ getProjectById: () => ({ id: "p" }) }) };
    if (id === "@/components/comments/comment-create") return { CommentCreate: Comment };
    if (id === "./helper") return { useWorkItemCommentOperations: () => ({}) };
    if (id === "./activity-comment-root") return { IssueActivityCommentRoot: List };
    return new Proxy({}, { get: () => () => null });
  }, api);
  return api.IssueActivity({ workspaceSlug: "w", projectId: "p", issueId: "i", disabled });
}
test("详情和预览共用紧凑活动区，取消空白最低高度和默认工具栏展开", () => {
  const tree = load("asc", false),
    all = nodes(tree);
  assert.equal(tree.type, "section");
  assert.match(tree.props.className, /work-item-activity/);
  assert.match(tree.props.className, /min-w-0/);
  assert.ok(all.every((node) => !node.props?.className?.includes("min-h-[200px]")));
  const editor = all.find((node) => node.type === Comment);
  assert.equal(editor.props.showToolbarInitially, false);
});
test("活动排序和只读权限仍准确，紧凑布局不丢失评论操作", () => {
  for (const order of ["asc", "desc"]) {
    const all = nodes(load(order, false)),
      comment = all.findIndex((node) => node.type === Comment),
      list = all.findIndex((node) => node.type === List);
    assert.equal(comment < list, order === "desc");
    assert.equal(all.filter((node) => node.type === Comment).length, 1);
  }
  assert.equal(nodes(load("asc", true)).filter((node) => node.type === Comment).length, 0);
});
