import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const compile = (path) =>
  ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
const utils = {};
new Function("require", "exports", compile("../../packages/utils/src/datetime.ts"))(require, utils);
function* nodes(value) {
  if (Array.isArray(value)) {
    for (const child of value) yield* nodes(child);
  } else if (value?.props) {
    yield value;
    yield* nodes(value.props.children);
  }
}
function render(instant, params = new URLSearchParams()) {
  const realDate = Date,
    urls = [],
    updates = [];
  globalThis.Date = class extends realDate {
    constructor(...args) {
      super(...(args.length ? args : [instant]));
    }
  };
  try {
    const api = {},
      mocks = {
        react: { useState: (value) => [value, () => {}] },
        "mobx-react": { observer: (value) => value },
        "react-router": {
          useParams: () => ({ workspaceSlug: "test" }),
          useSearchParams: () => [params, (value) => updates.push(value)],
        },
        "@plane/utils": utils,
        "@/hooks/store/use-project": {
          useProject: () => ({ joinedProjectIds: ["project"], getProjectById: () => ({ name: "测试" }) }),
        },
        "@/components/quality/use-collection-pagination": {
          useCollectionPagination: () => ({ page: 1, perPage: 20, paging: { onChange() {} } }),
        },
        swr: {
          default: (url) => {
            urls.push(url);
            return {};
          },
        },
      };
    new Function("require", "exports", compile("../core/components/analytics/project-period-report.tsx"))(
      (name) =>
        mocks[name] ?? (name === "react/jsx-runtime" ? require(name) : new Proxy({}, { get: () => () => null })),
      api
    );
    return { tree: api.ProjectPeriodReport(), urls, updates };
  } finally {
    globalThis.Date = realDate;
  }
}
test("项目报表默认区间及本周、本月、近30天均使用北京时间，与查询时区一致", () => {
  const before = process.env.TZ;
  try {
    for (const zone of ["UTC", "America/Los_Angeles", "Asia/Shanghai"]) {
      process.env.TZ = zone;
      for (const [instant, end, month, week, recent] of [
        ["2026-01-01T00:01:00+08:00", "2026-01-01", "2026-01-01", "2025-12-29", "2025-12-03"],
        ["2026-03-01T07:59:59+08:00", "2026-03-01", "2026-03-01", "2026-02-23", "2026-01-31"],
        ["2024-03-01T00:01:00+08:00", "2024-03-01", "2024-03-01", "2024-02-26", "2024-02-01"],
      ]) {
        const view = render(instant),
          query = new URL(view.urls[0], "http://fixture").searchParams;
        assert.equal(query.get("timezone"), "Asia/Shanghai");
        assert.equal(query.get("start"), month, `${zone}: ${instant}`);
        assert.equal(query.get("end"), end);
        for (const [label, start] of [
          ["本周", week],
          ["本月", month],
          ["近30天", recent],
        ]) {
          [...nodes(view.tree)].find((node) => node.type === "button" && node.props.children === label).props.onClick();
          assert.equal(view.updates.at(-1).get("start"), start);
          assert.equal(view.updates.at(-1).get("end"), end);
        }
      }
    }
  } finally {
    if (before === undefined) delete process.env.TZ;
    else process.env.TZ = before;
  }
});
test("显式选择的纯日期区间不因设备时区偏移", () => {
  const view = render("2026-01-01T00:01:00+08:00", new URLSearchParams({ start: "2025-12-25", end: "2025-12-31" }));
  const query = new URL(view.urls[0], "http://fixture").searchParams;
  assert.equal(query.get("start"), "2025-12-25");
  assert.equal(query.get("end"), "2025-12-31");
});
