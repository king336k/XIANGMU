import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
function group(rows) {
  const exports = {};
  new Function(
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/quality/timeline-inspection-groups.ts", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }
    ).outputText
  )(exports);
  return exports.groupSuccessfulInspections(rows, (row) => row.process);
}
const inspect = (id, run = "run-a", overrides = {}) => ({
  id,
  process: { stage: "inspect", run_id: run, command: { status: "done", ok: true, exit_code: 0 }, ...overrides },
});
test("only consecutive successful inspections in the same real task form a collapsed group", () => {
  const rows = [
    inspect("one"),
    inspect("two"),
    { id: "assignment" },
    inspect("three"),
    inspect("four", "run-b"),
    inspect("five", "run-b"),
  ];
  const result = group(rows);
  assert.deepEqual(
    result.map((entry) => ({ grouped: entry.grouped, ids: entry.items.map((item) => item.id) })),
    [
      { grouped: true, ids: ["one", "two"] },
      { grouped: false, ids: ["assignment"] },
      { grouped: false, ids: ["three"] },
      { grouped: true, ids: ["four", "five"] },
    ]
  );
  assert.deepEqual(
    result.flatMap((entry) => entry.items),
    rows
  );
});
test("failed unknown repair verify and missing task ids always stay outside inspection grouping", () => {
  for (const process of [
    { stage: "repair" },
    { stage: "verify" },
    { stage: "completed" },
    { run_id: "" },
    { command: { status: "done", ok: false, exit_code: 0 } },
    { command: { status: "done", ok: true, exit_code: 1 } },
    { command: { status: "delivered", ok: true, exit_code: 0 } },
    { command: { status: "done", ok: null, exit_code: 0 } },
    { command: { status: "done", ok: true } },
  ]) {
    const rows = [inspect("before"), inspect("boundary", "run-a", process), inspect("after")];
    assert.equal(
      group(rows).every((entry) => !entry.grouped),
      true
    );
  }
});
