import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const repoRoot = fileURLToPath(new URL("../../../../", import.meta.url));
const read = (path) => readFileSync(resolve(repoRoot, path), "utf8");
const requireWeb = createRequire(resolve(repoRoot, "ProjectFront/package.json"));

test("cycle overview and shared progress chart do not render the known English labels", () => {
  const regressions = {
    "ProjectFront/core/components/cycles/active-cycle/progress.tsx": [
      "name: group.title",
      '"Work items"',
      ">{group}</span>",
      "} closed`",
    ],
    "ProjectFront/core/components/cycles/active-cycle/productivity.tsx": ["Pending points", "Pending work items"],
    "ProjectFront/core/components/core/sidebar/progress-chart.tsx": [
      "Current ${plotTitle}",
      "Ideal ${plotTitle}",
      'label: "Date"',
      'label: "Completion"',
    ],
  };
  for (const [file, labels] of Object.entries(regressions)) {
    for (const label of labels) assert.ok(!read(file).includes(label), `${file}: ${label}`);
  }
});

test("module and cycle date filter labels retain their payload values", () => {
  const source = read("packages/constants/src/filter.ts");
  for (const label of ["1 周后", "2 周后", "1 个月后", "2 个月后"]) assert.ok(source.includes(`name: "${label}"`));
  for (const value of [
    "1_weeks;after;fromnow",
    "2_weeks;after;fromnow",
    "1_months;after;fromnow",
    "2_months;after;fromnow",
  ]) {
    assert.ok(source.includes(`value: "${value}"`));
  }
});

test("timezone dates use full numeric dates for default and month-name formats", () => {
  const ts = requireWeb("typescript");
  const source = read("ProjectFront/core/hooks/use-timezone-converter.tsx");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const context = {
    exports: {},
    require: (name) => {
      if (name === "react") return { useCallback: (callback) => callback };
      if (name === "@/hooks/store/user") return { useUser: () => ({ data: { user_timezone: "Asia/Shanghai" } }) };
      if (name === "@/hooks/store/use-project")
        return { useProject: () => ({ getProjectById: () => ({ timezone: "UTC" }) }) };
      return requireWeb(name);
    },
  };
  vm.runInNewContext(compiled, context);
  const { renderFormattedDateInUserTimezone: render } = context.exports.useTimeZoneConverter("project");
  assert.equal(render("2026-10-08T02:00:00Z"), "2026/10/08");
  assert.equal(render("2026-10-08T02:00:00Z", "MMM dd, yyyy"), "2026/10/08");
  assert.equal(render("2026-10-08T02:00:00Z", "MMMM do"), "2026/10/08");
  assert.equal(render("2026-10-08T18:00:00Z"), "2026/10/09");
  assert.equal(render("2026-10-08T02:00:00Z", "HH:mm"), "10:00");
});
