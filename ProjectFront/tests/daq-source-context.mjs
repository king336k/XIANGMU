import { AgentReportText } from "./agent-report-text-fixture.js";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
function load() {
  const exports = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/quality/collaboration-panel.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }
    ).outputText
  )(
    (id) =>
      id === "./agent-report-text"
        ? { AgentReportText }
        : id === "react/jsx-runtime"
          ? require(id)
          : new Proxy({}, { get: () => () => null }),
    exports
  );
  return exports;
}
function text(node) {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(text).join("");
  return text(node.props?.children);
}
const source = {
  id: "s",
  source_system: "ENGRAM_DAQ",
  source_instance: "dp-production",
  record_type: "daq_incident",
  record_id: "16:internal-event-id",
  task_id: "24",
  package_id: "",
  device: "",
};
test("来源卡展示DAQ上报人快照和Session引用，不显示外部项目任务关联", () => {
  const { SourceCard } = load();
  const result = text(
    SourceCard({
      source: {
        ...source,
        source_context: {
          platformProjectId: 9,
          platformProjectName: "生产采集项目",
          platformTaskId: 24,
          platformTaskName: "机械臂抓取任务",
          sourceReference: "本地Session-A",
          reporter: { id: 16, username: "采集员甲" },
        },
      },
    })
  );
  assert.ok(result.includes("采集员甲"));
  assert.ok(!result.includes("生产采集项目") && !result.includes("机械臂抓取任务"));
  assert.ok(result.includes("上报引用") && result.includes("本地Session-A"));
  assert.ok(!result.includes("internal-event-id"));
});
test("无Session故障不显示伪数据包编号，普通来源继续显示原关联字段", () => {
  const { SourceCard } = load();
  const event = text(
    SourceCard({
      source: {
        ...source,
        source_context: {
          platformProjectId: 9,
          platformProjectName: "采集项目",
          platformTaskId: null,
          platformTaskName: "",
          sourceReference: "",
        },
      },
    })
  );
  assert.ok(!event.includes("上报引用"));
  assert.ok(!event.includes("数据包："));
  const ordinary = text(
    SourceCard({
      source: { ...source, record_type: "session", source_context: null, package_id: "package-4", device: "robot-8" },
    })
  );
  assert.ok(ordinary.includes("package-4") && ordinary.includes("robot-8"));
});
