import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import test from "node:test";
const roots = [
  "../core/components",
  "../../packages/i18n/src/locales/zh-CN",
  "../../packages/constants/src",
  "../../packages/ui/src",
  "../../packages/editor/src",
].map((p) => fileURLToPath(new URL(p, import.meta.url)));
function files(p) {
  return readdirSync(p, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? files(join(p, e.name)) : /\.(tsx?|json)$/.test(e.name) ? [join(p, e.name)] : []
  );
}
test("主应用可见中文统一管理员、技术员和采集员，不增设另一套管理员身份", () => {
  const violations = [];
  for (const p of roots.flatMap(files)) {
    if (p.endsWith("/quality/duty-summary.ts")) continue; // Input-only historical label aliases, never rendered.
    const s = readFileSync(p, "utf8");
    if (/实例管理员|平台管理员|项目管理员|工作空间管理员|研发技术员/.test(s)) violations.push(p);
  }
  assert.deepEqual(violations, []);
});
