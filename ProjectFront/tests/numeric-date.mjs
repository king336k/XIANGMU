import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../../packages/utils/package.json", import.meta.url));
const ts = require("typescript");
const source = readFileSync(new URL("../../packages/utils/src/datetime.ts", import.meta.url), "utf8");
const code = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const mod = { exports: {} };
new Function("require", "exports", "module", code)(require, mod.exports, mod);
const dates = mod.exports;
assert.equal(dates.renderFormattedDate("2026-10-08"), "2026/10/08");
assert.equal(dates.renderFormattedDateWithoutYear("2026-10-08"), "2026/10/08");
assert.equal(dates.formatDateRange(new Date(2026, 9, 8), new Date(2026, 9, 18)), "2026/10/08 - 2026/10/18");
assert.equal(dates.renderFormattedPayloadDate("2026-10-08"), "2026-10-08", "Wire dates remain ISO");
assert.match(dates.calculateTimeAgo(new Date(Date.now() - 120000)), /分钟前/);
assert.equal(dates.calculateTimeAgo("invalid-date"), "");
assert.match(dates.calculateTimeAgoShort(new Date(Date.now() - 120000)), /分钟前/);
console.log("Numeric display dates and unchanged ISO payload dates passed.");

process.env.TZ = "Asia/Shanghai";
assert.equal(dates.renderNumericDateTime("2026-11-07T04:34:56Z"), "2026/11/07 12:34");
assert.equal(dates.renderNumericDateTime("2026-11-07T23:45:00Z"), "2026/11/08 07:45");
assert.equal(dates.renderNumericDateTime("2026-11-07"), "2026/11/07", "Date-only records must not invent a midnight creation time");
assert.equal(dates.renderNumericDateTime("invalid"), "—");
