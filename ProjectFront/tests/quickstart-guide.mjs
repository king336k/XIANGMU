import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const walk = (node) =>
  !node || typeof node !== "object"
    ? []
    : Array.isArray(node)
      ? node.flatMap(walk)
      : [node, ...walk(node.props?.children)];
const icon = () => null;
function render(complete, admin) {
  const exports = {},
    writes = [];
  const mocks = {
    react: React,
    "react/jsx-runtime": require("react/jsx-runtime"),
    "mobx-react": { observer: (x) => x },
    "next/link": { __esModule: true, default: "a" },
    "next/navigation": { useParams: () => ({ workspaceSlug: "w" }) },
    "@plane/constants": {
      EUserPermissions: { ADMIN: 20, MEMBER: 15 },
      EUserPermissionsLevel: { WORKSPACE: "workspace" },
    },
    "@plane/hooks": {
      useLocalStorage: () => ({
        storedValue: { hide: false, visited_workspace: complete, visited_profile: complete },
        setValue: (x) => writes.push(x),
      }),
    },
    "@plane/i18n": { useTranslation: () => ({ t: (x) => x }) },
    "@plane/propel/icons": { MembersPropertyIcon: icon, CheckIcon: icon, ProjectIcon: icon, CloseIcon: icon },
    "lucide-react": { Hotel: icon },
    "@plane/utils": { cn: () => "", getFileURL: (x) => x },
    "@/hooks/store/use-command-palette": { useCommandPalette: () => ({ toggleCreateProjectModal() {} }) },
    "@/hooks/store/use-project": { useProject: () => ({ joinedProjectIds: ["p"] }) },
    "@/hooks/store/use-workspace": { useWorkspace: () => ({ currentWorkspace: { total_members: 2 } }) },
    "@/hooks/store/user": { useUser: () => ({ data: { id: "u", email: "u@invalid" } }) },
    "@/components/settings/use-settings-permissions": {
      useSettingsPermissions: () => ({ allowPermissions: () => admin }),
    },
  };
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/home/widgets/empty-states/no-projects.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }
    ).outputText
  )((id) => mocks[id] || require(id), exports);
  return { nodes: walk(exports.NoProjectsEmptyState()), writes };
}
test("快速入门已完成仍可重复打开，管理员入口准确指向当前工作区", () => {
  const { nodes, writes } = render(true, true);
  assert.ok(nodes.some((n) => n.type === "button" && n.props.children === "home.empty.create_project.cta"));
  for (const href of ["/w/settings/", "/w/settings/members", "/settings/profile/general"]) {
    const link = nodes.find((n) => n.type === "a" && n.props.href === href);
    assert.ok(link, href);
    if (link.props.onClick) {
      link.props.onClick();
      link.props.onClick();
    }
  }
  assert.ok(writes.length >= 2);
  assert.ok(nodes.some((n) => n.props?.["aria-label"] === "已访问"));
});
test("普通成员不出现工作区管理入口，仍可操作个人设置", () => {
  const { nodes } = render(false, false);
  assert.ok(!nodes.some((n) => n.type === "a" && n.props.href === "/w/settings/"));
  assert.ok(nodes.some((n) => n.type === "a" && n.props.href === "/settings/profile/general"));
});
