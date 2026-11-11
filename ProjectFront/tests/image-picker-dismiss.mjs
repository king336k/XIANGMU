import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
function handler(file, name, values) {
  const source = readFileSync(new URL(`../core/components/core/${file}`, import.meta.url), "utf8"),
    tree = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let target;
  function visit(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(tree) === name) target = node.initializer;
    ts.forEachChild(node, visit);
  }
  visit(tree);
  assert.ok(target);
  const code = ts.transpileModule(`const handle=${target.getText(tree)};`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText;
  return new Function(...Object.keys(values), `${code};return handle;`)(...Object.values(values));
}
test("项目和个人封面通过点击空白处关闭时清除待上传图片，上传中不关闭", () => {
  for (const uploading of [false, true]) {
    let selected = { name: "draft.png" },
      opened = true;
    const close = handler("image-picker-popover.tsx", "handleClose", {
      isOpen: true,
      isImageUploading: uploading,
      setIsOpen: (v) => {
        opened = v;
      },
      setImage: (v) => {
        selected = v;
      },
    });
    close();
    assert.equal(opened, uploading);
    assert.equal(selected === null, !uploading);
  }
});
test("工作空间标志关闭时立即清除草稿，上传和移除过程中不关闭", () => {
  for (const busy of [false, true]) {
    let selected = { name: "logo.png" },
      closed = false;
    const close = handler("modals/workspace-image-upload-modal.tsx", "handleClose", {
      isImageUploading: busy,
      isRemoving: false,
      setImage: (v) => {
        selected = v;
      },
      onClose: () => {
        closed = true;
      },
      setIsImageUploading() {},
      setTimeout: () => {},
    });
    close();
    assert.equal(closed, !busy);
    assert.equal(selected === null, !busy);
  }
});
