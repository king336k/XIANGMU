import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  api = {};
new Function(
  "exports",
  ts.transpileModule(
    readFileSync(new URL("../core/components/issues/issue-layouts/kanban/arrangement.ts", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }
  ).outputText
)(api);
test("55条按5条分为11页，最后一页准确，页面不会越翻越长", () => {
  const ids = Array.from({ length: 55 }, (_, i) => `item-${i + 1}`);
  const first = api.boardPageWindow(ids, 55, 5, false, 1),
    last = api.boardPageWindow(ids, 55, 5, false, 11);
  assert.equal(first.pageCount, 11);
  assert.deepEqual(first.visibleIds, ids.slice(0, 5));
  assert.deepEqual(last.visibleIds, ids.slice(50, 55));
  assert.equal(last.visibleIds.length, 5);
  assert.equal(last.from, 51);
  assert.equal(last.to, 55);
});
test("向下展开最多两倍且不超过20条，其他记录通过分页查看", () => {
  const ids = Array.from({ length: 55 }, (_, i) => `${i}`);
  assert.equal(api.boardPageWindow(ids, 55, 5, true, 1).visibleIds.length, 10);
  assert.equal(api.boardPageWindow(ids, 55, 15, true, 1).visibleIds.length, 20);
  assert.equal(api.boardPageWindow(ids, 55, 5, true, 6).visibleIds.length, 5);
});
test("跨服务端批次按需补取，不足一页及删除后页码自动归位", () => {
  const ids = Array.from({ length: 30 }, (_, i) => `${i}`);
  assert.equal(api.boardPageWindow(ids, 55, 5, false, 7).needsFetch, true);
  assert.equal(api.boardPageWindow(ids, 55, 5, false, 6).needsFetch, false);
  assert.equal(api.boardPageWindow(ids, 10, 5, false, 11).page, 2);
  const short = api.boardPageWindow(["a", "b"], 2, 5, false, 1);
  assert.equal(short.pageCount, 1);
  assert.equal(short.visibleIds.length, 2);
});
