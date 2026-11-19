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
test("public summary and readable basis keep technical identifiers in a separate closed disclosure", () => {
  const id = "95f89e89-3d92-4f6c-a6aa-9b95fddfcd88";
  const original = `Agent 远程处理：已修复\n故障：初始化失败\n已处理：初值由3.3改为0.3\n待验证：实际遥操作\n详细依据：\n日志：joint limit violation\nrun_id=${id}`;
  const html = renderToStaticMarkup(React.createElement(AgentReportText, { content: original }));
  assert.match(html, /<summary[^>]*>关键依据<\/summary>/);
  assert.match(html, /<summary[^>]*>技术追踪<\/summary>/);
  assert.doesNotMatch(html, /<details[^>]*open/);
  const primary = html.split("<details")[0];
  assert.doesNotMatch(primary, new RegExp(id));
  assert.doesNotMatch(primary, /joint limit violation/);
  assert.match(html, /joint limit violation/);
  assert.match(html, new RegExp(id));
});
