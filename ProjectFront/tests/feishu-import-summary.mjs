import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const stubs = new Map();
const stub = (name) => {
  if (!stubs.has(name)) stubs.set(name, () => null);
  return stubs.get(name);
};
function load(file, resolve = require) {
  const exports = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(`../core/components/quality/${file}.tsx`, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )(resolve, exports);
  return exports;
}
function form(preview, api = {}) {
  let cursor = 0;
  const state = [{ name: "previous.pdf" }, preview];
  const exports = load("document-import-form", (id) => {
    if (id === "react")
      return {
        ...React,
        useState(initial) {
          const at = cursor++;
          if (!(at in state)) state[at] = initial;
          return [
            state[at],
            (value) => {
              state[at] = value;
            },
          ];
        },
      };
    if (id === "react/jsx-runtime") return require(id);
    if (id === "./api") return { qualityApi: api, errorMessage: String };
    if (id === "./feishu-import-summary") return load("feishu-import-summary");
    return new Proxy({}, { get: (_, key) => (key === "fieldClass" ? "field" : stub(key)) });
  });
  return exports.DocumentImportForm({ base: "/q/", resource: "knowledge", onClose() {}, onSaved: async () => {} });
}
function nodes(tree) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
const complete = {
  id: "feishu-import",
  status: "preview",
  valid: true,
  files: [],
  errors: [],
  source_url: "https://example.feishu.cn/docx/example",
  rows: [{ title: "来源正文", content: "第一段" }],
  extraction: {
    format: "feishu_docx",
    segment_count: 2,
    image_count: 1,
    attachment_count: 3,
    files_complete: true,
    failures: [],
  },
};
test("飞书部分读取失败即使valid=true也不能确认，正常完整预检可确认", () => {
  assert.equal(typeof form(complete).props.onSubmit, "function");
  const failed = {
    ...complete,
    extraction: { ...complete.extraction, failures: [{ block_id: "b1", stage: "image", error: "无权限" }] },
  };
  assert.equal(form(failed).props.onSubmit, undefined);
  const labels = nodes(form(failed)).flatMap((node) => [node.props?.children].flat());
  assert.ok(labels.includes("预检未通过"));
  assert.ok(!labels.includes("预检通过"));
});
test("飞书完整性false或缺失时不能确认，旧feishu格式采用相同限制", () => {
  for (const format of ["feishu_docx", "feishu"]) {
    for (const files_complete of [false, undefined]) {
      assert.equal(
        form({ ...complete, extraction: { ...complete.extraction, format, files_complete } }).props.onSubmit,
        undefined
      );
    }
  }
});
test("服务端范围错误即使完整性误报true也不能确认", () => {
  assert.equal(
    form({
      ...complete,
      errors: [{ row: 1, error: "附件读取失败", range: { block_id: "b1", stage: "attachment" } }],
    }).props.onSubmit,
    undefined
  );
});
test("飞书快照复用受控文件预览，旧本地PDF选择不会开放飞书OCR", () => {
  const files = [{ id: "snapshot", name: "飞书快照.json", kind: "original", download_url: "/private/snapshot/" }];
  const tree = form({ ...complete, files });
  assert.equal(nodes(tree).find((node) => node.type === stub("DocumentSourceFiles")).props.files, files);
  assert.equal(
    nodes(tree).some((node) => node.type === stub("DocumentOcrReview")),
    false
  );
});
test("非飞书完整性字段不影响既有PDF导入和OCR审核拦截", () => {
  const pdf = { ...complete, source_url: "", extraction: { format: "pdf" } };
  assert.equal(typeof form(pdf).props.onSubmit, "function");
  assert.equal(
    nodes(form(pdf)).some((node) => node.type === stub("DocumentOcrReview")),
    true
  );
  assert.equal(
    form({ ...pdf, extraction: { format: "pdf", ocr: { status: "completed", requires_review: true } } }).props.onSubmit,
    undefined
  );
});
test("入口称从飞书文档读取，不再声称仅读正文", () => {
  const strings = nodes(form(complete))
    .flatMap((node) => [node.props?.children].flat())
    .filter((x) => typeof x === "string")
    .join(" ");
  assert.match(strings, /从飞书文档读取/);
  assert.doesNotMatch(strings, /飞书仅读取正文|从飞书正文读取/);
});
test("飞书摘要显示真实分项数，图片未OCR只提示回源核对", () => {
  const { FeishuImportSummary } = load("feishu-import-summary");
  const { renderToStaticMarkup } = require("react-dom/server");
  const html = renderToStaticMarkup(
    React.createElement(FeishuImportSummary, { extraction: complete.extraction, errors: [] })
  );
  assert.match(html, /飞书文档 · 2段正文 · 1张图片 · 3份附件/);
  assert.match(html, /图片尚未识别文字/);
  assert.doesNotMatch(html, /识别图片文字|已理解图片|files_complete|feishu_docx/);
});
test("飞书零计数保留真实零，缺计数显示待核对", () => {
  const { FeishuImportSummary } = load("feishu-import-summary");
  const { renderToStaticMarkup } = require("react-dom/server");
  const html = renderToStaticMarkup(
    React.createElement(FeishuImportSummary, {
      extraction: { format: "feishu_docx", files_complete: true, segment_count: 0, image_count: 0 },
    })
  );
  assert.match(html, /0段正文 · 0张图片 · 待核对份附件/);
  assert.doesNotMatch(html, /图片尚未识别文字/);
});
test("失败以中文阶段展示，block_id只放折叠定位详情，未知stage不泄漏内部阶段名", () => {
  const { FeishuImportSummary } = load("feishu-import-summary");
  const extraction = {
    ...complete.extraction,
    files_complete: false,
    failures: [
      { block_id: "private-block-123", stage: "image", error: "无权读取图片" },
      { block_id: "private-block-456", stage: "internal_stage_999", error: "读取失败" },
    ],
  };
  const tree = FeishuImportSummary({ extraction, errors: [] });
  const { renderToStaticMarkup } = require("react-dom/server");
  const html = renderToStaticMarkup(tree);
  assert.match(html, /有内容未完整读取，暂不能确认导入/);
  assert.match(html, /读取图片：无权读取图片/);
  assert.doesNotMatch(html, /internal_stage_999/);
  const outside = nodes(tree)
    .filter((node) => node.type === "li")
    .map((node) => {
      const children = [node.props.children].flat().filter((child) => child?.type !== "details");
      return renderToStaticMarkup(React.createElement("div", null, children));
    })
    .join("");
  assert.doesNotMatch(outside, /private-block/);
  assert.match(html, /<details\b[^>]*>[\s\S]*private-block-123/);
});
test("只有preview errors范围时仍显示失败阶段与定位，不丢错误文本", () => {
  const { FeishuImportSummary } = load("feishu-import-summary");
  const { renderToStaticMarkup } = require("react-dom/server");
  const errors = [{ row: 1, error: "附件下载失败", range: { block_id: "attachment-block", stage: "attachment" } }];
  const html = renderToStaticMarkup(
    React.createElement(FeishuImportSummary, { extraction: { ...complete.extraction, files_complete: false }, errors })
  );
  assert.match(html, /读取附件：附件下载失败/);
  assert.match(html, /attachment-block/);
});

test("真实飞书错误码转为中文，未知内部错误不直接显示", () => {
  const { FeishuImportSummary } = load("feishu-import-summary");
  const { renderToStaticMarkup } = require("react-dom/server");
  for (const [error, expected] of [
    ["upstream_denied_or_failed", "文件无法读取，请检查飞书权限或文件是否仍存在。"],
    ["upstream_error_content", "飞书返回了错误页面，请核对文件权限后重新读取。"],
    ["merged_table_requires_review", "暂不支持合并单元格，请拆分表格后重新读取。"],
    ["future_internal_failure_123", "此处内容未能读取，请核对原文后重试。"],
  ]) {
    const html = renderToStaticMarkup(React.createElement(FeishuImportSummary, {
      extraction: { ...complete.extraction, files_complete: false, failures: [{ stage: "block", block_id: "img", error }] },
    }));
    assert.ok(html.includes(expected), html);
    assert.ok(!html.includes(error), html);
  }
});
