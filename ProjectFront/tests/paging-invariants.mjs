import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
function load(path, mocks = {}) {
  const api = {};
  new Function(
    "exports",
    "require",
    ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText
  )(api, (id) => mocks[id]);
  return api;
}
const board = load("../core/components/issues/issue-layouts/kanban/arrangement.ts"),
  sheet = load("../core/components/issues/issue-layouts/spreadsheet/pagination.ts", { "../kanban/arrangement": board });
test("分页不变量：0到1000条全页拼接无缺失无重复、每页不越界、输入不改变", () => {
  for (const total of [0, 1, 4, 5, 6, 9, 10, 11, 19, 20, 21, 49, 50, 51, 99, 100, 101, 275, 999, 1000])
    for (const size of [20, 50, 100]) {
      const input = Array.from({ length: total }, (_, i) => String(i)),
        before = [...input],
        seen = [];
      const pages = sheet.spreadsheetPageWindow(input, total, size, 1).pageCount;
      for (let page = 1; page <= pages; page++) {
        const result = sheet.spreadsheetPageWindow(input, total, size, page);
        assert.ok(result.visibleIds.length <= size);
        assert.equal(result.needsFetch, false);
        seen.push(...result.visibleIds);
        assert.ok(
          total === 0
            ? result.from === 0 && result.to === 0
            : result.from >= 1 && result.to <= total && result.from <= result.to
        );
      }
      assert.deepEqual(seen, input);
      assert.equal(new Set(seen).size, total);
      assert.deepEqual(input, before);
    }
});
test("看板排列不变量：各布局任意前后上下移动保持全部栏且每栏只出现一次", () => {
  for (let count = 1; count <= 7; count++) {
    const ids = Array.from({ length: count }, (_, i) => String(i));
    for (const layout of ["horizontal", "two-columns", "single-column", "custom-rows"])
      for (const source of ids)
        for (const target of ids)
          for (const placement of ["before", "after", "above", "below"]) {
            const result = board.placeBoardGroup(ids, ids.slice(2), source, target, placement, layout);
            assert.deepEqual([...result.order].sort(), [...ids].sort());
            assert.equal(new Set(result.order).size, count);
            const rows = board.boardLayoutRows(result.order, result.layout, result.rowStarts);
            assert.deepEqual(rows.flat(), result.order);
            assert.ok(rows.every((row) => row.length > 0));
          }
  }
});
