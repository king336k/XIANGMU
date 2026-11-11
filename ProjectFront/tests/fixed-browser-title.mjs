import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");

test("切换工作空间、项目、工作项及空标题时标签名称均固定", () => {
  const source = readFileSync(new URL("../core/components/core/page-title.tsx", import.meta.url), "utf8");
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const exports = {}, document = { title: "之前的页面" };
  new Function("require", "exports", "document", code)((id) => id === "react"
    ? { useEffect: (effect) => effect() }
    : id === "@plane/constants" ? { SITE_NAME: "项目管理平台" } : require(id), exports, document);
  for (const title of ["111 - 首页", "产品研发示例 · 缺陷管理", "DEMO-R-1", undefined, ""]) {
    exports.PageHead({ title });
    assert.equal(document.title, "项目管理平台", String(title));
  }
});

function titleNodes(directory, found = []) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = new URL(entry.name + (entry.isDirectory() ? "/" : ""), directory);
    if (entry.isDirectory()) { if (entry.name !== "assets") titleNodes(path, found); continue; }
    if (!/\.tsx?$/.test(entry.name)) continue;
    const ast = ts.createSourceFile(path.pathname, readFileSync(path, "utf8"), ts.ScriptTarget.Latest, true);
    function belongsToMeta(node) {
      for (let parent = node.parent; parent; parent = parent.parent) {
        if (ts.isVariableDeclaration(parent)) return parent.name.getText(ast) === "meta";
      }
      return false;
    }
    function visit(node) {
      if (ts.isPropertyAssignment(node) && node.name.getText(ast) === "title" &&
          ts.isStringLiteral(node.initializer) && belongsToMeta(node)) found.push([path.pathname, node.initializer.text]);
      ts.forEachChild(node, visit);
    }
    visit(ast);
  }
  return found;
}
test("登录、邀请、初始化和错误页的路由元数据不会覆盖固定名称", () => {
  const titles = titleNodes(new URL("../app/", import.meta.url));
  assert.ok(titles.length >= 8);
  for (const [path, title] of titles) assert.equal(title, "项目管理平台", path);
});
