import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const exports = {};
new Function(
  "exports",
  ts.transpileModule(
    readFileSync(new URL("../core/components/quality/timeline-inspection-groups.ts", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }
  ).outputText
)(exports);
export const groupSuccessfulInspections = exports.groupSuccessfulInspections;
