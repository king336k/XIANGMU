import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../../packages/utils/package.json", import.meta.url)),
  ts = require("typescript");
const api = {};
new Function(
  "require",
  "exports",
  ts.transpileModule(readFileSync(new URL("../../packages/utils/src/datetime.ts", import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
)(require, api);
test("同一时间戳在不同时区设备均显示中国标准时间，纯日期及接口日期不偏移", () => {
  const before = process.env.TZ;
  try {
    for (const zone of ["UTC", "America/Los_Angeles", "Asia/Shanghai"]) {
      process.env.TZ = zone;
      assert.equal(api.renderFormattedDate("2026-11-07T23:45:00Z"), "2026/11/08");
      assert.equal(api.renderFormattedTime("2026-11-07T23:45:00Z"), "07:45");
      assert.equal(api.renderNumericDateTime("2026-11-07T23:45:00Z"), "2026/11/08 07:45");
      assert.equal(api.renderFormattedDate("2026-11-07"), "2026/11/07");
      assert.equal(api.renderFormattedPayloadDate("2026-11-07"), "2026-11-07");
    }
  } finally {
    if (before === undefined) delete process.env.TZ;
    else process.env.TZ = before;
  }
});
test("日常工作空间、项目、个人与报表页面不提供时区设置", () => {
  for (const path of [
    "workspace/settings/workspace-details.tsx",
    "project/form.tsx",
    "profile/sidebar.tsx",
    "analytics/project-period-report.tsx",
  ]) {
    const source = readFileSync(new URL(`../core/components/${path}`, import.meta.url), "utf8");
    assert.doesNotMatch(source, /<TimezoneSelect|name="timezone"|profile.details.time_zone|统计时区/);
  }
});
