import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
function load(name, mocks = {}) {
  const exports = {};
  const code = ts.transpileModule(
    readFileSync(new URL("../core/components/quality/" + name + ".tsx", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }
  ).outputText;
  const settingsPaths = {};
  new Function(
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/settings/management-paths.ts", import.meta.url), "utf8"),
      {
        compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
      }
    ).outputText
  )(settingsPaths);
  new Function("require", "exports", code)(
    (id) =>
      mocks[id] ??
      (id === "@/components/settings/management-paths" ? settingsPaths : undefined) ??
      (id.startsWith("./")
        ? new Proxy({}, { get: (_, key) => (key === "fieldClass" ? "field" : () => null) })
        : id === "lucide-react"
          ? new Proxy({}, { get: () => () => null })
          : id === "@/components/common/project-route-link"
            ? { ProjectRouteLink: () => null }
            : id === "@plane/utils"
              ? { renderNumericDateTime: () => "" }
              : require(id)),
    exports
  );
  return exports;
}
const row = {
  id: "d",
  code: "Q-D-1",
  title: "问题",
  status: "open",
  severity: "major",
  edit_version: 3,
  collaborators: [],
  events: [],
  resolution_kind: "fixed",
};
const context = {
  user_id: "manager",
  is_manager: true,
  capabilities: { manage_defect: true },
  members: [],
  issues: [],
};
const modules = load("defect-detail", {
  "./types": {
    can: (c, k) => !!c.capabilities?.[k],
    severityNames: { "": "待评估", major: "严重" },
    statusNames: { open: "待处理" },
  },
  "./shared": {
    Modal: ({ children }) => React.createElement("main", null, children),
    Badge: ({ label }) => React.createElement("span", null, label),
  },
  "./defect-disposition": {
    resolutionNames: { fixed: "按修复回归处理" },
    DefectDispositionPanel: ({ trigger }) =>
      trigger ? React.createElement("button", { "aria-label": "更改处理分类" }, trigger) : null,
  },
});
function detail(value = row, ctx = context) {
  return renderToStaticMarkup(
    React.createElement(modules.DefectDetail, {
      base: "/q/",
      value,
      context: ctx,
      projectUrl: "/p/",
      onClose() {},
      onEdit() {},
      onChanged: async () => {},
    })
  );
}
test("详情右侧各项都有明确的独立编辑入口", () => {
  const html = detail();
  for (const name of ["调整严重程度", "更改处理分类", "指派技术负责人", "编辑影响版本", "编辑修复版本", "关联测试用例"])
    assert.ok(html.includes('aria-label="' + name + '"'), name);
});
test("只读账号及关闭记录不显示可保存属性入口", () => {
  for (const html of [
    detail(row, { ...context, is_manager: false, capabilities: {} }),
    detail({ ...row, status: "closed" }),
  ])
    assert.ok(!html.includes('aria-label="编辑影响版本"'));
});
test("新增字段快捷保存只提交单字段和版本，不改变其他属性", async () => {
  await Promise.all(
    [
      ["affected_build", "affected_build", "v1"],
      ["fixed_build", "fixed_build", "v2"],
      ["case", "case_id", "case1"],
    ].map(async ([field, key, data]) => {
      const writes = [];
      const api = load("defect-quick-edit", {
        "./api": {
          qualityApi: {
            write: async (...args) => {
              writes.push(args);
              return row;
            },
          },
        },
        "./types": { can: () => true, severityNames: {} },
        "./shared": { Modal: () => null, Field: () => null, fieldClass: "field" },
      });
      const tree = api.DefectQuickEdit({
        base: "/q/",
        context,
        value: row,
        field,
        projectUrl: "/p/",
        onClose() {},
        onSaved: async () => {},
      });
      const form = new FormData();
      form.set(key, data);
      await tree.props.onSubmit(form);
      assert.deepEqual(writes[0], ["/q/defects/d/", { [key]: data, expected_version: 3 }, "patch"]);
    })
  );
});

test("问题内容默认展开可折叠，DAQ模板拆成紧凑属性与正文", () => {
  const description =
    "问题范围：遥操与 DAQ\n\n发生阶段：其他情况\n\n受影响模块：尚不确定\n\n异常类型：其他问题\n\n现场描述：第一行\n第二行\n\n时间说明：以日志为准。";
  const html = renderToStaticMarkup(React.createElement(modules.DefectDescription, { description }));
  assert.match(html, /<details[^>]*open/);
  assert.match(html, /<summary/);
  for (const text of [
    "现象与重现步骤",
    "问题范围",
    "遥操与 DAQ",
    "发生阶段",
    "受影响模块",
    "异常类型",
    "现场描述",
    "第一行",
    "第二行",
    "以日志为准。",
  ])
    assert.ok(html.includes(text), text);
  assert.equal((html.match(/<dt/g) || []).length, 4);
});

test("普通描述和不完整模板保留原文，不丢额外行或空行", () => {
  for (const description of [
    "手工描述\n\n重现：点击开始\n预期：正常\n实际：失败",
    "问题范围：DAQ\n\n现场描述：不完整模板",
    "问题范围：DAQ\n\n自定义字段：保留我\n\n现场描述：额外内容",
  ]) {
    const html = renderToStaticMarkup(React.createElement(modules.DefectDescription, { description }));
    assert.ok(html.includes(description));
    assert.equal((html.match(/<dt/g) || []).length, 0);
  }
});

test("待评估属性保留明确文字，自动判级依据可查看", () => {
  const html = detail({ ...row, severity: "", severity_origin: "pending", severity_reason: "等待材料" });
  assert.ok(html.includes("待评估"));
  const automatic = detail({
    ...row,
    severity: "major",
    severity_origin: "diagnostic",
    severity_reason: "原始写入失败",
    severity_job_id: "job-one",
  });
  assert.ok(automatic.includes("自动判级"));
  assert.ok(automatic.includes("原始写入失败"));
});
