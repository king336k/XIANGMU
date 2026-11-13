import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
const source = readFileSync(
  new URL("../core/components/workspace/sidebar/projects-list-item.tsx", import.meta.url),
  "utf8"
);
const file = ts.createSourceFile("sidebar.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
function find(node, predicate) {
  return [...(predicate(node) ? [node] : []), ...node.getChildren(file).flatMap((child) => find(child, predicate))];
}
test("项目菜单区分已归档任务导航和带确认的归档项目操作", () => {
  const menus = find(
    file,
    (n) => ts.isJsxElement(n) && n.openingElement.tagName.getText(file) === "CustomMenu.MenuItem"
  );
  const work = menus.find((n) => n.getText(file).includes("已归档任务"));
  assert.ok(work, "已有归档入口必须明确只针对工作项");
  assert.match(work.getText(file), /archives\/issues/);
  const project = menus.find((n) => n.getText(file).includes("归档项目"));
  assert.ok(project, "项目应有独立归档入口");
  assert.match(project.getText(file), /setArchiveProjectModal\(true\)/);
  const modal = find(
    file,
    (n) => ts.isJsxSelfClosingElement(n) && n.tagName.getText(file) === "ArchiveRestoreProjectModal"
  )[0];
  assert.ok(modal, "复用已有确认与权限流程");
  const attributes = modal.attributes.getText(file);
  assert.match(attributes, /isOpen=\{archiveProjectModalOpen\}/);
  assert.match(attributes, /projectId=\{projectId\}/);
  assert.match(attributes, /\barchive\b/);
});
