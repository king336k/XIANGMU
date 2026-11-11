import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
const api = {};
new Function(
  "require",
  "exports",
  ts.transpileModule(readFileSync(new URL("../core/store/pages/project-page.ts", import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
)((id) => {
  if (id === "mobx") return { computed: () => {}, makeObservable: () => {} };
  if (id === "mobx-utils") return { computedFn: (fn) => fn };
  if (id === "@plane/constants")
    return { EPageAccess: { PUBLIC: 0, PRIVATE: 1 }, EUserPermissions: { MEMBER: 15, ADMIN: 20 } };
  if (id === "@/services/page") return { ProjectPageService: class {} };
  if (id === "./base-page")
    return {
      BasePage: class {
        constructor(store, page) {
          Object.assign(this, page);
          this.rootStore = store;
        }
        get isCurrentUserOwner() {
          return this.owned_by === "u";
        }
      },
    };
  return require(id);
}, api);
function page(write, role = 20, other = {}) {
  return new api.ProjectPage(
    { router: { workspaceSlug: "w" }, user: { permission: { getProjectRoleByWorkspaceSlugAndProjectId: () => role } } },
    { id: "doc", project_ids: ["p"], owned_by: "u", access: 0, can_write: write, ...other }
  );
}
test("后端只读标记优先于原生管理员和文档创建人，所有内容修改入口一致关闭", () => {
  for (const writable of [false, undefined]) {
    const doc = page(writable);
    for (const field of [
      "canCurrentUserEditPage",
      "canCurrentUserDuplicatePage",
      "canCurrentUserLockPage",
      "canCurrentUserChangeAccess",
      "canCurrentUserArchivePage",
      "canCurrentUserDeletePage",
      "canCurrentUserMovePage",
      "isContentEditable",
    ])
      assert.equal(Boolean(doc[field]), false, field);
    assert.equal(doc.canCurrentUserAccessPage, true);
  }
});
test("合法编辑仍受文档可见范围、锁定和归档限制", () => {
  assert.equal(page(true, 15).isContentEditable, true);
  assert.equal(page(true, 15, { is_locked: true }).isContentEditable, false);
  assert.equal(page(true, 15, { archived_at: "2026/11/08" }).isContentEditable, false);
  assert.equal(page(true, 15, { access: 1, owned_by: "other" }).isContentEditable, false);
  assert.equal(page(true, 15, { access: 1, owned_by: "u" }).isContentEditable, true);
});
