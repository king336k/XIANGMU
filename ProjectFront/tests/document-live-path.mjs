import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
const source = readFileSync(new URL("../../packages/constants/src/endpoints.ts", import.meta.url), "utf8");
function config(env) {
  const api = {};
  new Function(
    "exports",
    "process",
    ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
  )(api, { env });
  return api;
}
test("未指定协作路径时连接现有/live服务，显式根路径和自定义路径仍保留", () => {
  assert.equal(config({}).LIVE_BASE_PATH, "/live");
  assert.equal(config({ VITE_LIVE_BASE_PATH: "" }).LIVE_BASE_PATH, "");
  assert.equal(config({ VITE_LIVE_BASE_PATH: "/realtime" }).LIVE_BASE_PATH, "/realtime");
});
