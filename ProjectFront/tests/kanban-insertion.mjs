import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
const api = {};
new Function(
  "exports",
  ts.transpileModule(
    readFileSync(new URL("../core/components/issues/issue-layouts/kanban/arrangement.ts", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }
  ).outputText
)(api);
test("第二栏插入第一栏前，原第一栏右移，所有栏不交换丢失", () => {
  assert.deepEqual(api.insertBoardGroup(["a", "b", "c", "d"], "b", "a", "before"), ["b", "a", "c", "d"]);
  assert.deepEqual(api.insertBoardGroup(["a", "b", "c", "d"], "a", "c", "after"), ["b", "c", "a", "d"]);
  assert.deepEqual(api.insertBoardGroup(["a", "b", "c", "d"], "c", "b", "before"), ["a", "c", "b", "d"]);
});
test("向下拖动创建下一排，同行插入仍按原宽度，空行自动去除", () => {
  const result = api.placeBoardGroup(["a", "b", "c", "d"], [], "b", "a", "below", "horizontal");
  assert.deepEqual(result.order, ["a", "c", "d", "b"]);
  assert.deepEqual(result.rowStarts, ["b"]);
  assert.equal(result.layout, "custom-rows");
  assert.deepEqual(api.boardRows(result.order, result.rowStarts), [["a", "c", "d"], ["b"]]);
  const move = api.placeBoardGroup(result.order, result.rowStarts, "d", "a", "below", "custom-rows");
  assert.deepEqual(api.boardRows(move.order, move.rowStarts), [["a", "c"], ["d"], ["b"]]);
});
test("两列里的向下放置保留已有其他排，列顺序及行边界能保存恢复", () => {
  const result = api.placeBoardGroup(["a", "b", "c", "d"], [], "a", "c", "below", "two-columns");
  assert.deepEqual(api.boardRows(result.order, result.rowStarts), [["b"], ["c", "d"], ["a"]]);
  const stored = api.normalizeBoardArrangement(result);
  assert.equal(stored.layout, "custom-rows");
  assert.deepEqual(stored.rowStarts, result.rowStarts);
});

test("自由分行可以明确恢复横向并排，清除行位置但保留当前列顺序", () => {
  const module = {};
  let patch;
  const code = ts.transpileModule(
    readFileSync(
      new URL("../core/components/issues/issue-layouts/kanban/arrangement-control.tsx", import.meta.url),
      "utf8"
    ),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
  ).outputText;
  new Function("require", "exports", code)(
    (id) =>
      id === "./arrangement"
        ? api
        : id === "./use-arrangement"
          ? {
              useBoardArrangement: () => ({
                layout: "custom-rows",
                order: ["b", "a"],
                rowStarts: ["a"],
                update: (value) => {
                  patch = value;
                },
              }),
            }
          : require(id),
    module
  );
  const root = module.KanbanArrangementControl({ groupBy: "state" });
  root.props.children[0].props.children[1].props.onChange({ target: { value: "horizontal" } });
  assert.deepEqual(patch, { layout: "horizontal", rowStarts: [] });
  assert.equal(api.boardInitialCount({ layout: "horizontal" }), 5);
  assert.equal(api.boardPageWindow(Array(55).fill("x"), 55, 5, true, 1).visibleIds.length, 10);
});

test("列表不分组切换看板自动按状态，已有有效分组不覆盖", () => {
  assert.deepEqual(api.kanbanGroupingPatch(null), { group_by: "state", sub_group_by: null });
  assert.deepEqual(api.kanbanGroupingPatch(undefined), { group_by: "state", sub_group_by: null });
  assert.equal(api.kanbanGroupingPatch("priority"), undefined);
});
