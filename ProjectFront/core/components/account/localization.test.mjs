import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import vm from "node:vm";

const root = fileURLToPath(new URL("../../../../", import.meta.url));
const requireWeb = createRequire(resolve(root, "ProjectFront/package.json"));
const ts = requireWeb("typescript");
const React = requireWeb("react");
const { renderToStaticMarkup } = requireWeb("react-dom/server");
const constants = {
  EAuthModes: { SIGN_IN: "SIGN_IN", SIGN_UP: "SIGN_UP" },
  EAuthSteps: { EMAIL: "EMAIL", PASSWORD: "PASSWORD", UNIQUE_CODE: "UNIQUE_CODE" },
  E_PASSWORD_STRENGTH: {
    EMPTY: "empty",
    LENGTH_NOT_VALID: "short",
    STRENGTH_NOT_VALID: "weak",
    STRENGTH_VALID: "valid",
  },
  SITE_NAME: "项目管理平台",
  SITE_DESCRIPTION: "管理需求、任务、缺陷、测试与项目知识。",
};
const widget = ({ children }) => React.createElement("div", null, children);
const fallback = new Proxy(widget, { get: (_, key) => (key === "__esModule" ? false : widget) });
function load(path, overrides = {}) {
  const source = readFileSync(resolve(root, path), "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    reportDiagnostics: true,
  });
  assert.equal(output.diagnostics.length, 0, path);
  const context = {
    exports: {},
    require: (name) => {
      if (overrides[name]) return overrides[name];
      if (name === "react" || name === "react/jsx-runtime") return requireWeb(name);
      if (name === "mobx-react") return { observer: (component) => component };
      if (name === "swr") return { __esModule: true, default: () => ({ data: undefined, isLoading: false }) };
      if (name === "next-themes") return { useTheme: () => ({ resolvedTheme: "light" }) };
      if (name === "@plane/constants" || name === "@/helpers/authentication.helper") return constants;
      if (name === "@plane/i18n")
        return { useTranslation: () => ({ t: (key) => ({ version: "版本", "common.join": "加入" })[key] ?? key }) };
      if (name === "@/services/workspace.service") return { WorkspaceService: class {} };
      if (name === "next/link" || name === "@/layouts/default-layout") return { __esModule: true, default: widget };
      if (name === "package.json") return { version: "1.4.3" };
      if (name === "@/hooks/store/use-command-palette")
        return { useCommandPalette: () => ({ toggleCreateProjectModal() {} }) };
      if (name === "@/hooks/store/user")
        return { useUser: () => ({ data: { username: "User name", first_name: "Legacy name" } }) };
      if (name === "@/hooks/store/use-instance") return { useInstance: () => ({ config: { enable_signup: true } }) };
      if (name === "@plane/utils")
        return { cn: (...items) => items.filter((item) => typeof item === "string").join(" ") };
      if (name.endsWith("?url")) return "asset.svg";
      return fallback;
    },
  };
  vm.runInNewContext(output.outputText, context);
  return context.exports;
}
function render(component, props = {}) {
  return renderToStaticMarkup(React.createElement(component, props));
}

test("login and sign-up headers state the platform and action without marketing", () => {
  const { AuthHeader } = load("ProjectFront/core/components/account/auth-forms/auth-header.tsx");
  for (const mode of ["SIGN_IN", "SIGN_UP"])
    for (const step of ["EMAIL", "PASSWORD", "UNIQUE_CODE"]) {
      const html = render(AuthHeader, { authMode: mode, currentAuthStep: step });
      assert.ok(html.includes("项目管理平台"), html);
      assert.ok(html.includes(mode === "SIGN_IN" ? "登录" : "创建账号"), html);
      assert.ok(!/Plane|dimensions|Welcome/.test(html), html);
    }
});

test("deployment notice does not imply accepting Plane commercial terms", () => {
  const { TermsAndConditions } = load("ProjectFront/core/components/account/terms-and-conditions.tsx");
  const html = render(TermsAndConditions);
  assert.ok(html.includes("部署使用请遵循本单位账号与数据管理要求"), html);
  assert.ok(!/plane.so|Terms of Service|understand and agree/.test(html), html);
});

test("login footer describes the product without customer endorsements", () => {
  const { AuthFooter } = load("ProjectFront/core/components/auth-screens/footer.tsx");
  const html = render(AuthFooter);
  assert.ok(html.includes("需求、任务、缺陷、测试与项目知识"), html);
  assert.ok(!/Plane|10,000|Sony|Dolby/.test(html), html);
});

test("help about area preserves the upstream license attribution", () => {
  const { PlaneVersionNumber } = load("ProjectFront/core/components/global/version-number.tsx");
  const html = render(PlaneVersionNumber);
  assert.ok(html.includes("AGPL-3.0"), html);
  assert.ok(html.includes("https://github.com/makeplane/plane/blob/preview/LICENSE"), html);
});

test("production error explains recovery without promising automatic monitoring", () => {
  const { ProdErrorComponent } = load("ProjectFront/app/error/prod.tsx");
  const html = render(ProdErrorComponent, { onGoHome() {} });
  assert.ok(html.includes("页面暂时无法显示"), html);
  assert.ok(html.includes("管理员"), html);
  assert.ok(!/plane.so|track these errors|planepowers/.test(html), html);
});

test("welcome tour renders the platform name and preserves the user name", () => {
  const { TourRoot } = load("ProjectFront/core/components/onboarding/tour/root.tsx");
  const html = render(TourRoot, { onComplete() {} });
  assert.ok(html.includes("项目管理平台"), html);
  assert.ok(html.includes("User name"), html);
  assert.ok(!/Plane|try out|Product Tour/.test(html), html);
});

test("default metadata and manifests use the deployment product name", () => {
  const metadata = load("packages/constants/src/metadata.ts");
  assert.equal(metadata.SITE_NAME, "项目管理平台");
  assert.ok(metadata.SITE_DESCRIPTION.includes("需求、任务、缺陷、测试与项目知识"));
  for (const name of ["manifest.json", "site.webmanifest.json"]) {
    const manifest = JSON.parse(readFileSync(resolve(root, "ProjectFront/public", name), "utf8"));
    assert.equal(manifest.name, "项目管理平台");
  }
});

test("authentication banners keep API codes and encoded sign-in links", () => {
  const { authErrorHandler, EAuthenticationErrorCodes } = load("ProjectFront/helpers/authentication.helper.tsx");
  assert.equal(EAuthenticationErrorCodes.INVALID_PASSWORD, "5020");
  assert.equal(EAuthenticationErrorCodes.USER_ALREADY_EXIST, "5030");
  const invalid = authErrorHandler("5020");
  assert.equal(invalid.code, "5020");
  assert.ok(invalid.message.includes("密码不正确"));
  const existing = authErrorHandler("5030", "person+test@example.com");
  assert.equal(existing.message.props.children[1].props.href, "/sign-in?email=person%2Btest%40example.com");
  assert.ok(renderToStaticMarkup(existing.message).includes("该邮箱已注册"));
});

test("password labels customize display and preserve shared English defaults", () => {
  const { passwordLabels } = load("ProjectFront/core/components/account/password-labels.ts");
  const { PasswordStrengthIndicator } = load("packages/ui/src/form-fields/password/indicator.tsx", {
    "@plane/utils": {
      cn: () => "",
      getPasswordStrength: () => "weak",
      getPasswordCriteria: () => [{ key: "length", label: "Min 8 characters", isValid: false }],
    },
    "./helper": {
      getStrengthInfo: () => ({ message: "Password is weak", activeFragments: 1 }),
      getFragmentColor: () => "",
    },
  });
  const chinese = render(PasswordStrengthIndicator, { password: "example", labels: passwordLabels });
  assert.ok(chinese.includes("请按下方要求补充字符"), chinese);
  assert.ok(chinese.includes("至少 8 个字符"), chinese);
  const defaults = render(PasswordStrengthIndicator, { password: "example" });
  assert.ok(defaults.includes("Password is weak"), defaults);
  assert.ok(defaults.includes("Min 8 characters"), defaults);
});

test("access restriction pages explain the next step in Chinese", () => {
  const { NotAuthorizedView } = load("ProjectFront/core/components/auth-screens/not-authorized-view.tsx");
  assert.ok(render(NotAuthorizedView).includes("暂无此页面的访问权限"));
  const { NotAWorkspaceMember } = load("ProjectFront/core/components/auth-screens/workspace/not-a-member.tsx");
  const html = render(NotAWorkspaceMember);
  assert.ok(html.includes("管理员"), html);
  assert.ok(html.includes("查看待处理邀请"), html);
  assert.ok(!/Not Authorized|Check pending invites/.test(html), html);
});
