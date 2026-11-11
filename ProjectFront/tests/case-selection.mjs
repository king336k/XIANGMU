import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");

const source = new URL("../core/components/quality/case-selection.ts", import.meta.url);
const code = ts.transpileModule(readFileSync(source, "utf8"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { mergeCaseSelection } = await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);
const rows = Array.from({ length: 525 }, (_, index) => ({ id: `case-${index}`, title: `场景 ${index}` }));
const first = mergeCaseSelection([], rows.slice(0, 50), true);
const second = mergeCaseSelection(first, rows.slice(50, 100), true);
assert.equal(second.length, 100);
assert.deepEqual(mergeCaseSelection(second, rows.slice(0, 50), false), rows.slice(50, 100));
assert.equal(mergeCaseSelection(second, rows.slice(0, 50), true).length, 100);
assert.throws(() => mergeCaseSelection([], rows, true), /500/);
assert.equal(second.length, 100, "failed bulk addition must not change previous selection");
console.log("Case selection: cross-page preservation, scoped removal, deduplication and 500-item atomic limit passed.");
