import { AgentReportText } from "./agent-report-text-fixture.js";
import { groupSuccessfulInspections } from "./timeline-groups-fixture.js";
import { ConfigurationChangeDiff } from "./configuration-diff-fixture.js";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
function component(file, name, access, config) {
  const exports = {};
  const shell = ({ children, label }) => React.createElement("div", {}, label, children);
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(`../core/components/quality/${file}.tsx`, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((id) => {
    if (id === "./configuration-change-diff") return { ConfigurationChangeDiff };
    if (id === "./timeline-inspection-groups") return { groupSuccessfulInspections };
    if (id === "./agent-report-text") return { AgentReportText };
    if (id === "react") return React;
    if (id === "swr")
      return {
        default: (key) => ({
          data: Array.isArray(key)
            ? config
            : key.endsWith("/reminders/")
              ? access
              : key.includes("packages/")
                ? { count: 0, results: [] }
                : key.endsWith("/collaboration/")
                  ? [
                      {
                        id: "c",
                        actor: "技术员",
                        created_at: "2026-11-09",
                        content: "检查过程",
                        visibility: "internal",
                      },
                    ]
                  : [],
        }),
      };
    if (id === "@plane/utils") return { renderNumericDateTime: (s) => s };
    if (id === "@plane/ui")
      return { Button: ({ children, variant, size, ...props }) => React.createElement("button", props, children) };
    if (id === "./shared") return { Field: shell, Modal: shell, fieldClass: "field" };
    if (id === "./api") return { qualityApi: {}, errorMessage: String };
    if (id === "./types") return { can: (ctx, capability) => !!ctx.capabilities?.[capability] };
    if (id === "./attachment-upload") return { AttachmentUpload: () => null };
    if (id === "./package-form") return { PackageForm: () => null };
    return require(id);
  }, exports);
  return exports[name];
}
const value = { id: "d", status: "open", collaborators: [], edit_version: 1 };
const props = {
  base: "/api/q/",
  value,
  context: { user_id: "u", is_manager: false, capabilities: {} },
  onChanged: async () => {},
};
test("数采员只获得公开回复输入，内部员工获得明确的内部范围与站内催办", () => {
  const render = (access) =>
    renderToStaticMarkup(React.createElement(component("collaboration-panel", "CollaborationPanel", access), props));
  const collector = render({ can_internal_comment: false, can_public_comment: true, can_remind: false });
  assert.match(collector, /采集员可见回复/);
  assert.doesNotMatch(collector, /value="internal"|发送站内催办/);
  const internal = render({ can_internal_comment: true, can_public_comment: true, can_remind: true });
  assert.match(internal, /value="internal"/);
  assert.match(internal, /内部备注/);
  assert.match(internal, /10分钟内只提醒一次/);
  assert.match(internal, /发送站内催办/);
});
test("路由默认关闭，普通用户不出现无用控件，经理仍可配置本项目", () => {
  const View = component(
    "routing-panel",
    "RoutingPanel",
    {},
    {
      enabled: false,
      departments: [],
      components: [],
      department: "",
      component: "",
      version: 1,
      edit_version: 1,
      can_edit: false,
    }
  );
  assert.equal(renderToStaticMarkup(React.createElement(View, props)), "");
  const html = renderToStaticMarkup(
    React.createElement(View, { ...props, context: { ...props.context, is_manager: true } })
  );
  assert.match(html, /责任路由（可选）/);
  assert.match(html, /配置路由选项/);
  assert.doesNotMatch(html, /调整部门 \/ 组件/);
});
