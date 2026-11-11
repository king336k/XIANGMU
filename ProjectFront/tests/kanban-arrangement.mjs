import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const exports = {};
const source = readFileSync(
  new URL("../core/components/issues/issue-layouts/kanban/arrangement.ts", import.meta.url),
  "utf8"
);
new Function(
  "exports",
  ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } })
    .outputText
)(exports);
const {
  orderedBoardGroups,
  moveBoardGroup,
  normalizeBoardArrangement,
  boardArrangementKey,
  canDropBoardGroup,
  boardLoadState,
} = exports;
test("列顺序只排序有效状态，新增状态补入，删除状态不占位，不改变输入", () => {
  const groups = [{ id: "backlog" }, { id: "done" }, { id: "cancelled" }, { id: "new" }];
  assert.deepEqual(
    orderedBoardGroups(groups, ["done", "removed", "done", "backlog"]).map((g) => g.id),
    ["done", "backlog", "cancelled", "new"]
  );
  assert.deepEqual(
    groups.map((g) => g.id),
    ["backlog", "done", "cancelled", "new"]
  );
});
test("拖动与键盘前后移动均保留全部状态，无效目标不改变布局", () => {
  assert.deepEqual(moveBoardGroup(["a", "b", "c", "d"], "d", "b"), ["a", "d", "b", "c"]);
  assert.deepEqual(moveBoardGroup(["a", "b", "c", "d"], "a", "c"), ["b", "c", "a", "d"]);
  assert.deepEqual(moveBoardGroup(["a", "b"], "missing", "b"), ["a", "b"]);
});
test("个人布局按账号、页面与分组隔离，损坏设置安全回退", () => {
  assert.notEqual(
    boardArrangementKey("u1", "/w/p/a/issues/", "state"),
    boardArrangementKey("u2", "/w/p/a/issues/", "state")
  );
  assert.notEqual(
    boardArrangementKey("u1", "/w/p/a/issues/", "state"),
    boardArrangementKey("u1", "/w/p/b/issues/", "state")
  );
  assert.notEqual(
    boardArrangementKey("u1", "/w/p/a/issues/", "state"),
    boardArrangementKey("u1", "/w/p/a/issues/", "priority")
  );
  assert.deepEqual(normalizeBoardArrangement({ layout: "bad", order: ["a", null, "a", 2] }), {
    layout: "horizontal",
    order: ["a"],
  });
  assert.deepEqual(normalizeBoardArrangement(null), { layout: "horizontal", order: [] });
  assert.equal(normalizeBoardArrangement({ layout: "two-columns" }).layout, "two-columns");
});
test("拖动状态栏只接受同一看板的栏，不接收工作项或其他看板", () => {
  assert.equal(canDropBoardGroup({ type: "KANBAN_COLUMN", boardKey: "board", columnId: "a" }, "board", "b"), true);
  assert.equal(canDropBoardGroup({ type: "ISSUE", boardKey: "board", id: "a" }, "board", "b"), false);
  assert.equal(canDropBoardGroup({ type: "KANBAN_COLUMN", boardKey: "other", columnId: "a" }, "board", "b"), false);
  assert.equal(canDropBoardGroup({ type: "KANBAN_COLUMN", boardKey: "board", columnId: "b" }, "board", "b"), false);
});
test("几十个待排期准确区分已加载、总数与下一页，加载结束不重复请求", () => {
  assert.deepEqual(boardLoadState(30, 75, true), { loaded: 30, total: 75, hasMore: true });
  assert.deepEqual(boardLoadState(60, 75, true), { loaded: 60, total: 75, hasMore: true });
  assert.deepEqual(boardLoadState(75, 75, false), { loaded: 75, total: 75, hasMore: false });
  assert.equal(boardLoadState(30, 75, false).hasMore, false);
  assert.equal(boardLoadState(30, 75, undefined).hasMore, true);
  assert.deepEqual(boardLoadState(0, 0, undefined), { loaded: 0, total: 0, hasMore: false });
});
