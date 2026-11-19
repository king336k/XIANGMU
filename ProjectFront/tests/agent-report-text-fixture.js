import { reportSummary } from "./report-summary-fixture.js";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const exports = {};
new Function(
  "require",
  "exports",
  ts.transpileModule(
    readFileSync(new URL("../core/components/quality/agent-report-text.tsx", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }
  ).outputText
)((id) => (id === "./report-summary" ? reportSummary : require(id)), exports);
export const AgentReportText = exports.AgentReportText;
