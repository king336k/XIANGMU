import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const code = ts.transpileModule(
  readFileSync(new URL("../core/components/quality/pagination.ts", import.meta.url), "utf8"),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }
).outputText;
const exports = {};
new Function("exports", code)(exports);
test("一万页也只显示首尾、当前页及相邻页", () => {
  for (const total of [1, 2, 8, 100, 10000])
    for (const current of [1, Math.ceil(total / 2), total]) {
      const values = exports.pageNumbers(current, total);
      assert.ok(values.length <= 9);
      assert.equal(values[0], 1);
      assert.equal(values.at(-1), total);
      assert.ok(values.includes(current));
      const numbers = values.filter((value) => typeof value === "number");
      assert.equal(new Set(numbers).size, numbers.length);
      assert.ok(numbers.every((value) => value >= 1 && value <= total));
    }
});
test("每页20、50、100条；非法值回到50条", () => {
  for (const size of [20, 50, 100])
    assert.equal(exports.pageSize(new URLSearchParams({ per_page: String(size) })), size);
  for (const size of ["", "0", "-1", "Infinity", "1000000"])
    assert.equal(exports.pageSize(new URLSearchParams({ per_page: size })), 50);
});

test("请求页大小与界面统一，非法大值不能显示50却请求100", () => {
  const params = new URLSearchParams({ per_page: "200", page: "-3", search: "待确认", status: "open" });
  const next = exports.normalizedPageParams(params);
  assert.equal(next.get("per_page"), String(exports.pageSize(params)));
  assert.equal(next.get("page"), "1");
  assert.equal(next.get("search"), "待确认");
  assert.equal(next.get("status"), "open");
  assert.equal(params.get("per_page"), "200");
});
