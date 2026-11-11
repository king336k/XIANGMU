// node ProjectFront/core/components/knowledge/assistant-markdown.test.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../../../package.json", import.meta.url));
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
let source = "";
try {
  source = readFileSync(new URL("./assistant-markdown.tsx", import.meta.url), "utf8");
} catch {}
const code = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const mod = { exports: {} };
new Function("require", "exports", "module", code)(require, mod.exports, mod);
const { AssistantMarkdown } = mod.exports;
assert.equal(
  typeof AssistantMarkdown,
  "function",
  "Assistant Markdown must render without the incompatible remark-rehype chain"
);
const render = (content) => renderToStaticMarkup(React.createElement(AssistantMarkdown, { content }));
const markup = render(
  "# 排查\n\n**检查** `code`\n\n- 网络\n- 设备\n\n3. 验证\n4. 复测\n\n> 核对引用\n\n```bash\n<script>alert(1)</script>\n" +
    "x".repeat(2000) +
    "\n```"
);
assert.match(markup, /<h3[^>]*>排查<\/h3>/);
assert.match(markup, /<strong>检查<\/strong>/);
assert.match(markup, /<code[^>]*>code<\/code>/);
assert.match(markup, /<ul><li>网络<\/li><li>设备<\/li><\/ul>/);
assert.match(markup, /<ol start="3"><li>验证<\/li><li>复测<\/li><\/ol>/);
assert.match(markup, /<blockquote>/);
assert.match(markup, /<pre[^>]*overflow-x-auto/);
assert.match(markup, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
const hostile = render(
  '<script>alert(1)</script>\n<img src="https://tracker.invalid/a" onerror="alert(1)">\n\n![追踪](https://tracker.invalid/a) [注入](javascript:alert(1)) [编码](data:text/html,boom) [协议相对](//tracker.invalid/a) [安全](https://example.com/doc)'
);
assert.doesNotMatch(hostile, /<(?:img|script|iframe)\b/);
assert.doesNotMatch(hostile, /href="(?:javascript:|data:|\/\/)/);
assert.match(hostile, /外部图片已隐藏/);
assert.match(hostile, /href="https:\/\/example.com\/doc"/);
assert.match(hostile, /rel="noopener noreferrer"/);
assert.match(hostile, /referrerPolicy="no-referrer"/);
assert.match(render("```txt\n未闭合代码块"), /<pre[^>]*><code>未闭合代码块<\/code><\/pre>/);
const message = readFileSync(new URL("./assistant-message.tsx", import.meta.url), "utf8");
assert.doesNotMatch(message, /from ["']react-markdown["']/);
console.log(
  "Assistant Markdown SSR passed: formatting, long code, incomplete fences, escaped HTML, hidden images and safe links; no react-markdown import."
);
