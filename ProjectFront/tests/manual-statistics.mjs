import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
function all(t) {
  return !t || typeof t !== "object" ? [] : Array.isArray(t) ? t.flatMap(all) : [t, ...all(t.props?.children)];
}
test("人工验证单独统计，不冒充用例执行总数，且可进入对应缺陷验证", () => {
  const e = {};
  let link;
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/quality/quality-summary.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
    ).outputText
  )(
    (id) =>
      id === "react"
        ? { useState: () => [null, () => {}] }
        : id === "react"
          ? { ...React, useState: (v) => [v, () => {}] }
          : id === "react/jsx-runtime"
            ? require(id)
            : id === "./statistics-display"
              ? {
                  Distribution: ({ rows }) =>
                    React.createElement(
                      "div",
                      null,
                      rows.map((row) => React.createElement("span", { key: row.key }, `${row.name} ${row.count}`))
                    ),
                }
              : id === "./shared"
                ? { Badge: ({ label }) => React.createElement("span", null, label) }
                : id === "./types"
                  ? { resultNames: { passed: "通过", failed: "失败", pending: "未执行" } }
                  : new Proxy({}, { get: () => () => null }),
    e
  );
  const report = {
    case_count: 0,
    plan_count: 0,
    execution_count: 0,
    open_defects: 2,
    requirement_linked_cases: 0,
    summary: { total: 0, execution_rate: 0, pass_rate: 0 },
    manual_verification: { total: 1, passed: 1, failed: 0, pending: 0 },
    manual_execution_count: 2,
    definitions: {},
  };
  const tree = e.QualitySummary({ report, onNavigate: (next) => (link = next) }),
    html = renderToStaticMarkup(tree);
  assert.match(html, /人工验证/);
  assert.match(html, /当前 1 轮/);
  assert.match(html, /通过 1/);
  assert.match(html, /历史实测 2 次/);

  all(tree)
    .find((n) => n.props?.children === "查看缺陷验证")
    .props.onClick();
  assert.equal(link, "verification-results");
  assert.equal(report.summary.total, 0);
});
