import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";
import { AgentReportText } from "./agent-report-text-fixture.js";
const require = createRequire(new URL("../package.json", import.meta.url));
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
test("only known report headings are bold, numeric entries have their own lines and HTML stays text", () => {
  const original =
    "Agent 远程处理：已修复\n结论：采集已恢复\n原因与证据：配置不一致\n已执行操作：\n1. 修改配置 2. 执行复测\n复测：通过\n后续方案：观察\n修改位置：robot177 /home/robot/config.json:42\nhttp://example.com:8080\n<script>unsafe()</script>";
  const html = renderToStaticMarkup(React.createElement(AgentReportText, { content: original }));
  for (const label of [
    "Agent 远程处理：",
    "结论：",
    "原因与证据：",
    "已执行操作：",
    "复测：",
    "后续方案：",
    "修改位置：",
  ])
    assert.ok(html.includes(`>${label}</strong>`), label);
  assert.match(html, /<p[^>]*>1\. 修改配置<\/p><p[^>]*>2\. 执行复测<\/p>/);
  assert.doesNotMatch(html, /<strong[^>]*>http|<script>/);
  assert.match(html, /&lt;script&gt;unsafe\(\)&lt;\/script&gt;/);
  assert.match(html, /config.json:42/);
});
