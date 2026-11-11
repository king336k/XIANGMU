import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
function render(account) {
  const code = ts.transpileModule(
    readFileSync(
      new URL("../core/components/settings/profile/content/pages/general/form.tsx", import.meta.url),
      "utf8"
    ),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }
  ).outputText;
  const exports = {};
  const user = {
    username: "admin",
    first_name: "不应显示的名",
    last_name: "不应显示的姓",
    display_name: "不应显示的昵称",
    email: "internal@accounts.invalid",
  };
  const widget = ({ children }) => React.createElement("div", null, children);
  new Function("require", "exports", code)((name) => {
    if (name === "react" || name === "react/jsx-runtime") return require(name);
    if (name === "@/components/quality/duty-summary") {
      const module = {};
      new Function(
        "exports",
        ts.transpileModule(
          readFileSync(new URL("../core/components/quality/duty-summary.ts", import.meta.url), "utf8"),
          { compilerOptions: { module: ts.ModuleKind.CommonJS } }
        ).outputText
      )(module);
      return module;
    }
    if (name === "mobx-react") return { observer: (x) => x };
    if (name === "swr") return { __esModule: true, default: () => ({ data: account }) };
    if (name === "react-hook-form")
      return {
        Controller: () => null,
        useForm: () => ({ watch: () => "", control: {}, setValue() {}, handleSubmit: (fn) => fn }),
      };
    if (name === "@/hooks/store/user") return { useUser: () => ({ data: user, updateCurrentUser() {} }) };
    if (name === "@plane/i18n") return { useTranslation: () => ({ t: (x) => x }) };
    if (name === "@plane/types") return { EFileAssetType: { USER_COVER: "cover" } };
    return new Proxy({}, { get: () => widget });
  }, exports);
  return renderToStaticMarkup(React.createElement(exports.GeneralProfileSettingsForm, { user, profile: {} }));
}
test("个人资料显示本地账号，不提供外部账号维护入口", () => {
  const html = render({
    username: "admin",
    source_label: "项目管理平台账号",
    email: "admin@example.test",
    platform_role: "Manager",
    can_edit_identity: false,
    portal_url: "https://source.example",
    project_duties: [
      {
        project_id: "p",
        identifier: "APP",
        url: "/workspace/p/APP/issues/",
        project: "项目甲",
        roles: ["平台管理员", "技术员"],
      },
    ],
  });
  for (const value of ["admin", "项目管理平台账号", "admin@example.test", "项目甲", "管理员"])
    assert.ok(html.includes(value), value);
  for (const value of [
    "不应显示",
    "internal@",
    'name="first_name"',
    'name="last_name"',
    'name="display_name"',
    "显示名称",
    "停用账号",
    "数据平台角色",
    "在数据管理平台管理账号",
  ])
    assert.ok(!html.includes(value), value);
});
test("本平台无邮箱账号不显示占位邮箱或来源平台修改入口", () => {
  const html = render({
    username: "rd-user",
    source_label: "项目管理平台账号",
    email: "",
    can_edit_identity: true,
    portal_url: "",
    project_duties: [],
  });
  assert.ok(html.includes("rd-user"));
  assert.ok(!html.includes("邮箱") && !html.includes("accounts.invalid") && !html.includes("在数据管理平台管理账号"));
});

test("个人资料中的项目是可进入的链接，岗位保持说明文字", () => {
  const html = render({
    username: "demo",
    source_label: "项目管理平台账号",
    email: "",
    can_edit_identity: true,
    portal_url: "",
    project_duties: [
      { project_id: "p", identifier: "APP", url: "/workspace/p/APP/issues/", project: "项目甲", roles: ["项目经理"] },
    ],
  });
  assert.ok(html.includes('href="/workspace/p/APP/issues/"'));
  assert.ok(html.includes("我参与的项目") && html.includes("我的职责"));
});

test("项目名称与编号相同不会重复显示两行", () => {
  const html = render({
    username: "demo",
    source_label: "项目管理平台账号",
    email: "",
    can_edit_identity: true,
    portal_url: "",
    project_duties: [
      {
        project_id: "p",
        identifier: "111",
        url: "/workspace/p/111/issues/",
        project: "111",
        roles: ["平台管理员", "项目经理"],
      },
    ],
  });
  assert.equal((html.match(/>111</g) || []).length, 1);
  assert.ok(html.includes("项目管理"));
  assert.ok(!html.includes("安排需求、任务与测试，确认业务结果</span>"));
});
