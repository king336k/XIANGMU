import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const api = {};
const source = readFileSync(new URL("../core/components/quality/api.ts", import.meta.url), "utf8");
new Function(
  "require",
  "exports",
  ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
)(
  (name) =>
    name === "axios"
      ? { isAxiosError: (e) => e?.isAxiosError === true }
      : name === "@plane/constants"
        ? {}
        : { APIService: class {} },
  api
);

test("业务前置未满足时保留接口实际原因，不误导为刷新页面", () => {
  const error = {
    isAxiosError: true,
    response: { status: 409, data: { detail: "前置节点尚未完成，请先完成前置任务。" } },
  };
  assert.equal(api.errorMessage(error), "前置节点尚未完成，请先完成前置任务。");
});
test("空冲突回退仍保留原稿说明，403不透出服务端内部内容", () => {
  assert.ok(
    api.errorMessage({ isAxiosError: true, response: { status: 409, data: {} } }).includes("已填写的内容仍保留")
  );
  assert.equal(
    api.errorMessage({ isAxiosError: true, response: { status: 403, data: { detail: "内部原因" } } }),
    "您没有当前项目的操作权限，请联系项目经理。"
  );
});
