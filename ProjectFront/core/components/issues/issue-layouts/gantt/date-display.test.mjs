import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const repoRoot = fileURLToPath(new URL("../../../../../../", import.meta.url));
const requireWeb = createRequire(resolve(repoRoot, "ProjectFront/package.json"));

test("timeline date previews use numeric dates and 24-hour time", () => {
  const ts = requireWeb("typescript");
  const source = readFileSync(resolve(repoRoot, "ProjectFront/core/components/gantt-chart/data/index.ts"), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const context = { exports: {}, require: () => ({ EStartOfTheWeek: { SUNDAY: 0 } }) };
  vm.runInNewContext(compiled, context);
  const date = new Date(2026, 9, 8, 14, 5);
  assert.equal(context.exports.datePreview(date), "2026/10/08");
  assert.equal(context.exports.datePreview(date, true), "2026/10/08 14:05");
  assert.equal(context.exports.timePreview(new Date(2026, 0, 1, 0, 3)), "00:03");
});
