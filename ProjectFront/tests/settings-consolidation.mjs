import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
function load() {
  const exp = {};
  new Function(
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/settings/member-management-data.ts", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }
    ).outputText
  )(exp);
  return exp;
}
test("同一人员合并访问关系、来源和多岗位，只出现一行", () => {
  const { mergeMemberRows } = load();
  const rows = mergeMemberRows(
    [{ id: "membership", role: 15, member: { id: "u", username: "tester", display_name: "测试员" } }],
    [{ id: "workspace", role: 15, member: { id: "u", username: "tester" } }],
    [{ user_id: "u", roles: ["REGRESSION_TESTER", "TECHNICIAN"], is_administrator: false }],
    [{ id: "u", username: "tester", source: "数据平台" }],
    [{ id: "u", name: "测试员", business_roles: ["REGRESSION_TESTER"] }],
    "project"
  );
  assert.equal(rows.length, 1);
  assert.equal(rows[0].projectMembership.id, "membership");
  assert.equal(rows[0].workspaceMembership.id, "workspace");
  assert.deepEqual(rows[0].roles, ["REGRESSION_TESTER", "TECHNICIAN"]);
  assert.equal(rows[0].source, "数据平台");
});
test("全部人员与项目成员用同表，未加入人员不混入项目视图", () => {
  const { mergeMemberRows } = load();
  const people = [{ id: "new", username: "new" }];
  assert.equal(mergeMemberRows([], [], [], people, [], "project").length, 0);
  assert.equal(mergeMemberRows([], [], [], people, [], "accounts").length, 1);
});
test("加入后补多岗失败须说明首次岗位已保存，重试不重复加入", async () => {
  const { joinMemberWithRoles } = load();
  const calls = [],
    progress = {};
  let fail = true;
  const write = async (url, data) => {
    calls.push({ url, data });
    if (url.endsWith("roles/") && fail) throw Error("second save failed");
    return { user_id: "u" };
  };
  const args = {
    workspace: "w",
    projectId: "p",
    person: { user_id: "u" },
    roles: ["REGRESSION_TESTER", "TECHNICIAN"],
    progress,
    write,
  };
  await assert.rejects(joinMemberWithRoles(args), /已加入项目.*其余岗位未保存/);
  fail = false;
  await joinMemberWithRoles(args);
  assert.equal(calls.filter((x) => x.url.includes("quality-auth")).length, 1);
  assert.deepEqual(calls.at(-1).data.roles, args.roles);
});
test("可见主设置不再挂原三成员表，旧页仅重定向", () => {
  const read = (p) => readFileSync(new URL(`../${p}`, import.meta.url), "utf8");
  const unified = read("core/components/settings/unified-members.tsx");
  assert.doesNotMatch(unified, /<BusinessRolePanel|<AccountManager|<WorkspaceMembersList|<ProjectMemberList/);
  assert.match(unified, /<table/);
  assert.match(unified, /编辑权限/);
  assert.doesNotMatch(read("core/components/settings/profile/content/pages/security.tsx"), /<AccountManager/);
  assert.match(read("core/components/workspace/sidebar/user-menu-root.tsx"), /settings\/members/);
});

test("所有新生成的成员入口指向统一页，不再生成project成员页或账号页", () => {
  const read = (p) => readFileSync(new URL(`../${p}`, import.meta.url), "utf8");
  for (const file of [
    "core/components/workspace/sidebar/dropdown-item.tsx",
    "core/components/workspace/sidebar/workspace-menu-header.tsx",
    "core/components/workspace/sidebar/projects-list-item.tsx",
    "core/components/navigation/project-actions-menu.tsx",
    "core/components/navigation/app-rail-root.tsx",
    "core/components/project/card.tsx",
  ]) {
    assert.doesNotMatch(read(file), /t\("settings"\)|title: "设置"/, file);
  }
  for (const file of ["core/components/quality/defect-form.tsx", "core/components/quality/defect-quick-edit.tsx"]) {
    assert.match(read(file), /\/settings\/members\/\?project=/);
    assert.doesNotMatch(read(file), /quality\/\?tab=roles|\/members\/`/);
  }
  const nav = read("core/components/settings/workspace/sidebar/item-categories.tsx");
  assert.doesNotMatch(nav, /key: "accounts"|label="项目管理"/);
});

const nodes = (t) =>
  !t || typeof t !== "object" ? [] : Array.isArray(t) ? t.flatMap(nodes) : [t, ...nodes(t.props?.children)];
function componentHarness(file, extra = {}) {
  const React = require("react"),
    stubMap = new Map(),
    state = [];
  let cursor = 0;
  const writes = [];
  const stub = (name) => {
    if (!stubMap.has(name)) stubMap.set(name, () => null);
    return stubMap.get(name);
  };
  const exp = {};
  new Function(
    "require",
    "exports",
    "FormData",
    ts.transpileModule(readFileSync(new URL(`../core/components/settings/${file}.tsx`, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )(
    (id) => {
      if (id === "react/jsx-runtime") return require(id);
      if (id === "react")
        return {
          ...React,
          useState: (initial) => {
            const at = cursor++;
            if (!(at in state)) state[at] = initial;
            return [state[at], (v) => (state[at] = v)];
          },
          useRef: (initial) => ({ current: initial }),
        };
      if (id === "@/components/quality/api")
        return { qualityApi: { write: async (...args) => writes.push(args) }, errorMessage: String };
      if (id === "./member-management-data") return load();
      return new Proxy({}, { get: (_, key) => (key === "fieldClass" ? "field" : stub(key)) });
    },
    exp,
    class {
      constructor(form) {
        this.form = form;
      }
      get(name) {
        return this.form.get(name);
      }
      getAll(name) {
        return this.form.getAll(name);
      }
    }
  );

  return {
    writes,
    stub,
    nodes,
    render() {
      cursor = 0;
      return exp.MemberPermissionsModal({
        person: {
          id: "u",
          username: "worker",
          roles: ["PROJECT_MANAGER", "REGRESSION_TESTER"],
          projectMembership: { id: "mp", role: 15, member: { id: "u" } },
        },
        workspace: "w",
        projectId: "p",
        currentUserId: "admin",
        canRoles: true,
        canAdmin: false,
        canWorkspaceAccess: false,
        canProjectAccess: false,
        onSaved: async () => {},
        onClose() {},
        ...extra,
      });
    },
  };
}
test("编辑入口多岗完整提交roles数组，普通项目经理没有全局管理员页签", async () => {
  const h = componentHarness("member-permissions-modal"),
    tree = h.render();
  const inputs = h.nodes(tree).filter((n) => n.type === "input" && n.props.name === "roles");
  assert.equal(inputs.length, 4);
  assert.equal(inputs.filter((n) => n.props.defaultChecked).length, 2);
  assert.ok(!h.nodes(tree).some((n) => n.props?.children === "管理员身份"));
  const save = h.nodes(tree).find((n) => n.type === h.stub("Button") && n.props.children === "保存业务岗位");
  assert.ok(save);
  const form = { getAll: () => ["TECHNICIAN", "REGRESSION_TESTER"] };
  save.props.onClick({ currentTarget: { form } });
  await Promise.resolve();
  await Promise.resolve();
  assert.deepEqual(h.writes, [
    [
      "/api/workspaces/w/projects/p/quality/roles/",
      { user_id: "u", roles: ["TECHNICIAN", "REGRESSION_TESTER"] },
      "post",
    ],
  ]);
});
test("管理员身份不再提供多岗写入口，无业务授权时只读岗位", () => {
  const admin = componentHarness("member-permissions-modal", {
    person: { id: "a", username: "admin", is_administrator: true, roles: [] },
  });
  assert.equal(admin.nodes(admin.render()).filter((n) => n.props?.name === "roles").length, 0);
  const denied = componentHarness("member-permissions-modal", { canRoles: false });
  assert.ok(denied.nodes(denied.render()).some((n) => n.type === "fieldset" && n.props.disabled));
  assert.ok(!denied.nodes(denied.render()).some((n) => n.props?.children === "保存业务岗位"));
});

test("真实原生成员UUID与嵌套响应均保留两个人员及membership主键", () => {
  const { mergeMemberRows } = load();
  const rows = mergeMemberRows(
    [
      { id: "pm1", role: 15, member: "u1" },
      { id: "pm2", role: 5, member: "u2" },
    ],
    [
      { id: "wm1", role: 15, member: { id: "u1", username: "one" } },
      { id: "wm2", role: 15, member: { id: "u2", username: "two" } },
    ],
    [{ user_id: "u1", roles: ["REGRESSION_TESTER"] }],
    [],
    [
      { id: "u1", name: "一", business_roles: ["REGRESSION_TESTER"] },
      { id: "u2", name: "二", business_roles: [] },
    ],
    "project"
  );
  assert.deepEqual(
    rows.map((p) => p.id),
    ["u1", "u2"]
  );
  assert.equal(rows[0].projectMembership.id, "pm1");
  assert.equal(rows[1].projectMembership.id, "pm2");
  assert.equal(rows[0].workspaceMembership.id, "wm1");
});
test("首次岗位已加入后改成单岗位重试必须写最终选择，切人也不复用上个人进度", async () => {
  const { joinMemberWithRoles } = load(),
    calls = [],
    progress = {};
  let fail = true;
  const write = async (url, data) => {
    calls.push({ url, data });
    if (url.endsWith("roles/") && fail) throw Error("fail");
    return { user_id: data.user_id };
  };
  const args = {
    workspace: "w",
    projectId: "p",
    person: { user_id: "old" },
    roles: ["REPORTER", "REGRESSION_TESTER"],
    progress,
    write,
  };
  await assert.rejects(joinMemberWithRoles(args));
  fail = false;
  await joinMemberWithRoles({ ...args, roles: ["REGRESSION_TESTER"] });
  assert.deepEqual(calls.at(-1).data.roles, ["REGRESSION_TESTER"]);
  await joinMemberWithRoles({ ...args, person: { user_id: "new" }, roles: ["TECHNICIAN", "REGRESSION_TESTER"] });
  assert.equal(calls.at(-1).data.user_id, "new");
  assert.equal(calls.filter((c) => c.url.includes("quality-auth")).length, 2);
});

test("停用功能快捷入口准确进入现有设置叶路由", () => {
  const files = {
    "views/(list)/page.tsx": "views",
    "pages/(list)/page.tsx": "pages",
    "cycles/(list)/page.tsx": "cycles",
    "intake/page.tsx": "intake",
    "modules/(list)/page.tsx": "modules",
  };
  for (const [file, leaf] of Object.entries(files)) {
    const source = readFileSync(
      new URL(`../app/(all)/[workspaceSlug]/(projects)/projects/(detail)/[projectId]/${file}`, import.meta.url),
      "utf8"
    );
    assert.ok(source.includes(`/features/${leaf}`));
    assert.ok(!source.includes("/features`"));
  }
});

test("停用账号或移出访问范围不显示仍可参与", () => {
  const { memberAccessLabel } = load();
  assert.equal(
    memberAccessLabel(
      {
        id: "u",
        username: "u",
        roles: [],
        workspaceMembership: { id: "w", role: 15, is_active: false, member: { id: "u" } },
      },
      false
    ),
    "已移出工作空间"
  );
  assert.equal(
    memberAccessLabel(
      {
        id: "u",
        username: "u",
        roles: [],
        projectMembership: { id: "p", role: 15, is_active: false, member: { id: "u" } },
      },
      true
    ),
    "已移出项目"
  );
  assert.equal(
    memberAccessLabel(
      {
        id: "u",
        username: "u",
        roles: [],
        workspaceMembership: { id: "w", role: 15, member: { id: "u", is_active: false } },
      },
      false
    ),
    "账号已停用"
  );
});
