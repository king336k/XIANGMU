import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const all = (tree) =>
  !tree || typeof tree !== "object"
    ? []
    : Array.isArray(tree)
      ? tree.flatMap(all)
      : [tree, ...all(tree.props?.children)];
function harness(context = {}, value = {}) {
  let cursor = 0;
  const states = [],
    exports = {},
    writes = [];
  const compiled = ts.transpileModule(
    readFileSync(new URL("../core/components/quality/defect-reassign.tsx", import.meta.url), "utf8"),
    {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }
  ).outputText;
  new Function("require", "exports", compiled)((id) => {
    if (id === "@/components/common/project-route-link") return { ProjectRouteLink: () => null };
    if (id === "@/components/settings/management-paths") {
      const helper = {};
      new Function(
        "exports",
        ts.transpileModule(
          readFileSync(new URL("../core/components/settings/management-paths.ts", import.meta.url), "utf8"),
          { compilerOptions: { module: ts.ModuleKind.CommonJS } }
        ).outputText
      )(helper);
      return helper;
    }
    if (id === "react")
      return {
        useState: (v) => {
          const i = cursor++;
          if (!(i in states)) states[i] = v;
          return [states[i], (nextValue) => (states[i] = nextValue)];
        },
      };
    if (id === "swr")
      return {
        default: () => ({
          data: {
            module_options: [
              { key: "daq", name: "DAQ" },
              { key: "teleop", name: "遥操" },
            ],
          },
        }),
      };
    if (id === "./api") return { qualityApi: { write: async (...args) => writes.push(args) } };
    if (id === "./shared") return { Modal: () => null, Field: () => null, fieldClass: "field" };
    return require(id);
  }, exports);
  return {
    writes,
    render() {
      cursor = 0;
      return exports.DefectReassign({
        base: "/api/workspaces/ws/projects/p/quality/",
        value: {
          id: "d",
          assignee_id: "self",
          module: { key: "daq", name: "DAQ" },
          edit_version: 8,
          status: "open",
          title: "现场异常",
          ...value,
        },
        context: {
          user_id: "self",
          is_manager: false,
          business_roles_enabled: true,
          members: [
            { id: "self", name: "当前技术员", business_roles: ["TECHNICIAN"] },
            { id: "next", name: "遥操技术员", business_roles: ["TECHNICIAN"] },
            { id: "tester", name: "测试员", business_roles: ["REGRESSION_TESTER"] },
          ],
          ...context,
        },
        onClose() {},
        onSaved: async () => {},
      });
    },
  };
}
test("当前负责人能改派一个技术员并同时确认模块，传递并发版本及原因", async () => {
  const h = harness();
  let tree = h.render();
  const select = (label) => all(tree).find((n) => n.type === "select" && n.props["aria-label"] === label);
  assert.equal(
    all(select("技术负责人"))
      .filter((n) => n.type === "option")
      .some((n) => n.props.value === "tester"),
    false
  );
  select("技术负责人").props.onChange({ target: { value: "next" } });
  select("责任模块").props.onChange({ target: { value: "teleop" } });
  tree = h.render();
  const form = new FormData();
  form.set("reason", "排查确认属于输入控制问题");
  await tree.props.onSubmit(form);
  assert.deepEqual(h.writes, [
    [
      "/api/workspaces/ws/projects/p/quality/defects/d/reassign/",
      {
        assignee_id: "next",
        module_key: "teleop",
        reason: "排查确认属于输入控制问题",
        expected_version: 8,
      },
    ],
  ]);
});
test("普通旁观成员、已关闭和已归档缺陷不提供改派提交，经理允许", () => {
  for (const [context, value] of [
    [{ user_id: "other" }, {}],
    [{}, { status: "closed" }],
    [{}, { archived_at: "now" }],
  ])
    assert.equal(harness(context, value).render().props.onSubmit, undefined);
  assert.equal(typeof harness({ user_id: "manager", is_manager: true }).render().props.onSubmit, "function");
  assert.equal(
    typeof harness({ user_id: "admin", is_manager: false, is_administrator: true }).render().props.onSubmit,
    "function"
  );
});
