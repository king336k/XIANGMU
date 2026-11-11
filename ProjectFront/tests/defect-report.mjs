import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const dateUtils = {};
new Function(
  "require",
  "exports",
  ts.transpileModule(readFileSync(new URL("../../packages/utils/src/datetime.ts", import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
)(require, dateUtils);
function load() {
  const code = ts.transpileModule(
    readFileSync(new URL("../core/components/quality/defect-report.ts", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS } }
  ).outputText;
  const exports = {};
  new Function("require", "exports", code)((name) => {
    assert.equal(name, "@plane/utils");
    return dateUtils;
  }, exports);
  return exports.defectReport;
}
test("新增趋势补齐30个自然日，零值不伪造新增，跨月跨年连续", () => {
  const report = load()(
    {
      total: 4,
      unclosed: 3,
      by_status: [{ value: "closed", count: 1 }],
      by_severity: [],
      opened_by_day: [
        { date: "2025-12-31", count: 2 },
        { date: "2026-01-02", count: 1 },
      ],
    },
    new Date("2026-01-02T00:01:00Z")
  );
  assert.equal(report.trend.length, 30);
  assert.equal(report.trend.at(-1).date, "2026-01-02");
  assert.equal(report.trend[0].date, "2025-12-04");
  assert.equal(report.trend.find((x) => x.date === "2026-01-01").count, 0);
  assert.equal(report.recentTotal, 3);
  assert.equal(report.closedPercent, 25);
});
test("零缺陷显示0且不会出现NaN、Infinity或假占比", () => {
  const report = load()(
    { total: 0, unclosed: 0, by_status: [], by_severity: [], opened_by_day: [] },
    new Date("2026-11-07T12:00:00Z")
  );
  assert.equal(report.closedPercent, 0);
  assert.equal(report.recentTotal, 0);
  assert.equal(report.awaitingRegression, 0);
  assert.equal(
    report.trend.every((x) => x.count === 0),
    true
  );
});
test("关闭率只统计已关闭，待回归不冒充完成", () => {
  const report = load()({
    total: 10,
    unclosed: 8,
    by_status: [
      { value: "resolved", count: 5 },
      { value: "closed", count: 2 },
      { value: "open", count: 3 },
    ],
    by_severity: [],
    opened_by_day: [],
  });
  assert.equal(report.awaitingRegression, 5);
  assert.equal(report.closedPercent, 20);
  assert.equal(report.closed, 2);
});

test("北京时间凌晨当天新增不能丢失，跨月跨年窗口与后端最近30天对齐", () => {
  const before = process.env.TZ;
  try {
    for (const zone of ["UTC", "America/Los_Angeles", "Asia/Shanghai"]) {
      process.env.TZ = zone;
      for (const [instant, today, first] of [
        ["2026-01-01T00:00:00+08:00", "2026-01-01", "2025-12-03"],
        ["2026-03-01T07:59:59+08:00", "2026-03-01", "2026-01-31"],
        ["2024-03-01T00:01:00+08:00", "2024-03-01", "2024-02-01"],
      ]) {
        const report = load()(
          {
            total: 3,
            unclosed: 3,
            by_status: [],
            by_severity: [],
            opened_by_day: [
              { date: first, count: 1 },
              { date: today, count: 2 },
            ],
          },
          new Date(instant)
        );
        assert.equal(report.trend.at(-1).date, today, `${zone}: ${instant}`);
        assert.equal(report.trend[0].date, first);
        assert.equal(report.recentTotal, 3);
        assert.equal(report.trend.length, 30);
        assert.equal(new Set(report.trend.map((row) => row.date)).size, 30);
      }
    }
  } finally {
    if (before === undefined) delete process.env.TZ;
    else process.env.TZ = before;
  }
});
