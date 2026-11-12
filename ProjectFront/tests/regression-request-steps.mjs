import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("缺陷和计划只使用本平台测试验证，不请求外部数据回归", () => {
  for (const file of ["defect-detail", "plan-detail"]) {
    const source = readFileSync(new URL(`../core/components/quality/${file}.tsx`, import.meta.url), "utf8");
    assert.doesNotMatch(source, /data-regression-panel|DataEvidencePanel|DataRegressionPanel/);
  }
  const source = readFileSync(
    new URL("../core/components/quality/defect-verification-scope.tsx", import.meta.url),
    "utf8"
  );
  assert.match(source, /验收关闭/);
  assert.doesNotMatch(source, /value="data"|关联新采集Session|数据平台/);
});
