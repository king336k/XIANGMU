import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
const editorRoot = fileURLToPath(new URL("../../packages/editor/src", import.meta.url));
function files(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((item) =>
    item.isDirectory() ? files(path.join(dir, item.name)) : /\.tsx?$/.test(item.name) ? [path.join(dir, item.name)] : []
  );
}
test("所有共享编辑器可见文字、菜单和辅助标签使用中文，内部扩展名保持不变", () => {
  const internal = new Set([
      "listKeymap",
      "emoji",
      "customKeymap",
      "trailingNode",
      "titleEditorNavigation",
      "mainEditorNavigation",
    ]),
    found = [];
  for (const file of files(editorRoot)) {
    const source = readFileSync(file, "utf8"),
      tree = ts.createSourceFile(
        file,
        source,
        ts.ScriptTarget.Latest,
        true,
        file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS
      );
    function visit(node) {
      let text;
      if (ts.isJsxText(node)) text = node.text.trim();
      if (ts.isStringLiteral(node)) {
        const parent = node.parent;
        if (
          ts.isJsxAttribute(parent) &&
          /^(aria-label|placeholder|title|tooltipContent|tooltipHeading)$/.test(parent.name.getText(tree))
        )
          text = node.text;
        if (ts.isPropertyAssignment(parent) && /^(name|title|label|description)$/.test(parent.name.getText(tree)))
          text = node.text;
      }
      if (
        text &&
        /[A-Za-z]{3}/.test(text) &&
        !/[\u4e00-\u9fff]/.test(text) &&
        !internal.has(text) &&
        !/^\s*&\w+;\s*$/.test(text)
      )
        found.push(`${path.relative(editorRoot, file)}: ${text}`);
      ts.forEachChild(node, visit);
    }
    visit(tree);
  }
  assert.deepEqual(found, []);
});
test("图片校验与状态提示为中文，编辑器工具栏为图标提供对应中文名称", () => {
  for (const file of ["core/extensions/custom-image/components/uploader.tsx", "core/helpers/file.ts"]) {
    const source = readFileSync(path.join(editorRoot, file), "utf8");
    assert.doesNotMatch(
      source,
      /Add an image|Error loading image|Drop image here|Invalid file type|No file selected|File size too large/
    );
  }
  const toolbar = readFileSync(new URL("../core/components/editor/lite-text/toolbar.tsx", import.meta.url), "utf8");
  assert.match(toolbar, /aria-label={item.name}/);
});
