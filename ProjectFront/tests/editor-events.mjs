import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
test("编辑器菜单中文化保留浏览器事件方法", () => {
  let checked = 0;
  for (const file of ["ask-pi-menu.tsx", "menu.tsx"]) {
    const code = readFileSync(new URL(`../core/components/pages/editor/ai/${file}`, import.meta.url), "utf8");
    const ast = ts.createSourceFile(file, code, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    function visit(node) {
      if (ts.isPropertyAccessExpression(node) && node.name.text.startsWith("prevent")) {
        assert.equal(node.name.text, "preventDefault");
        checked++;
      }
      ts.forEachChild(node, visit);
    }
    visit(ast);
  }
  assert.ok(checked >= 4);
});
