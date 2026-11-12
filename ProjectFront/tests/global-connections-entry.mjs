import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const Connection = () => null;
const walk = (tree, predicate) =>
  !tree || typeof tree !== "object"
    ? []
    : Array.isArray(tree)
      ? tree.flatMap((n) => walk(n, predicate))
      : [...(predicate(tree) ? [tree] : []), ...walk(tree.props?.children, predicate)];
test("平台连接是全局配置，无需先选择项目或请求项目上下文", () => {
  const calls = [],
    exports = {};
  const mocks = {
    "mobx-react": { observer: (fn) => fn },
    "next/navigation": { useParams: () => ({ workspaceSlug: "w" }) },
    "react-router": { useSearchParams: () => [new URLSearchParams("project=stale"), () => {}] },
    swr: {
      default: (key) => {
        calls.push(key);
        return {};
      },
    },
    "@/hooks/store/use-project": { useProject: () => ({ joinedProjectIds: [], getPartialProjectById() {} }) },
    "@/components/quality/connection-settings": { ConnectionSettings: Connection },
    "@/components/quality/types": { canOpenQualityTab: () => false },
    "react/jsx-runtime": require("react/jsx-runtime"),
  };
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(
        process.env.PLATFORM_MANAGEMENT_SOURCE ||
          new URL("../core/components/settings/platform-management.tsx", import.meta.url),
        "utf8"
      ),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
    ).outputText
  )((id) => mocks[id] || new Proxy({}, { get: () => () => null }), exports);
  const tree = exports.PlatformManagement({ section: "connections" });
  assert.equal(walk(tree, (n) => n.type === "select").length, 0);
  const elements = walk(tree, (n) => n.type === Connection);
  assert.equal(elements.length, 1);
  assert.equal(elements[0].props.endpoint, "/api/quality-auth/connections/");
  assert.ok(
    calls.every((key) => key === null),
    JSON.stringify(calls)
  );
});
