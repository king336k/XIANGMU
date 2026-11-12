import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  api = {};
new Function(
  "exports",
  ts.transpileModule(readFileSync(new URL("../core/components/quality/duty-summary.ts", import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS },
  }).outputText
)(api);
test("管理员清楚显示最高权限，无需额外兼任经理", () => {
  const s = api.projectDutySummary(["平台管理员", "项目经理"]);
  assert.equal(s.label, "管理员");
  assert.equal(s.description, "管理权限，处理全部岗位业务");
  assert.equal(api.projectDutySummary(["平台管理员", "技术员"]).label, "管理员");
});
test("记录中的职责来自真实指派和参与关系，不能用账号管理员标签冒充负责人", () => {
  assert.deepEqual(api.recordDutyLabels({ userId: "demo", assigneeId: "other", canArrange: true }), ["项目统筹"]);
  assert.deepEqual(api.recordDutyLabels({ userId: "demo", assigneeId: "demo", kind: "测试计划" }), ["测试执行人"]);
  assert.deepEqual(api.recordDutyLabels({ userId: "demo", authorId: "demo", kind: "缺陷" }), ["上报人"]);
  assert.deepEqual(api.recordDutyLabels({ userId: "demo", collaboratorIds: ["demo"] }), ["协作者"]);
  assert.deepEqual(api.recordDutyLabels({ userId: "demo" }), ["查看记录"]);
});

test("页面职责只保留一个短标签，权限解释不铺成长句", () => {
  assert.equal(api.compactRecordDuty(["负责人", "创建人", "项目统筹"]), "负责");
  assert.equal(api.compactRecordDuty(["测试执行人", "项目统筹"]), "执行");
  assert.equal(api.compactRecordDuty(["查看记录"]), "");
});

test("项目职责说明简短且对应实际岗位", () => {
  assert.deepEqual(api.projectDutySummary(["项目经理"]), { label: "项目经理", description: "排期分工、跟进验收" });
  for (const role of ["技术员", "测试员"]) {
    const value = api.projectDutySummary([role]);
    assert.ok(value.description.length > 0 && value.description.length <= 12);
  }
});

test("没有专职岗位的普通项目成员保留基础反馈能力", () => {
  assert.deepEqual(api.projectDutySummary([]), { label: "项目成员", description: "反馈问题、补充材料" });
  assert.deepEqual(api.projectDutySummary(["数采员"]), { label: "项目成员", description: "反馈问题、补充材料" });
});
