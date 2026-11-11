import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
function render(component, name, mode) {
  let index = 0;
  const exports = {};
  const review = { id: "s", created_by_id: "author", status: "draft", revisions: [] };
  const code = ts.transpileModule(
    readFileSync(new URL(`../core/components/quality/${component}.tsx`, import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
  ).outputText;
  const Empty = () => null;
  const hooks = {
    ...React,
    useState: (initial) => {
      const i = index++;
      return [mode === "station" && i === 2 ? true : mode === "solution" && i === 1 ? review : initial, () => {}];
    },
  };
  new Function("require", "exports", code)(
    (id) =>
      id === "react"
        ? hooks
        : id === "swr"
          ? { default: () => ({ data: { results: [], count: 0 }, mutate() {} }) }
          : id === "./types"
            ? { can: () => true }
            : id === "./use-collection-pagination"
              ? { useCollectionPagination: () => ({ query: "page=1", paging: {} }) }
              : id === "./shared"
                ? {
                    Modal: ({ children }) => React.createElement("div", null, children),
                    Field: ({ children }) => React.createElement("div", null, children),
                    Paging: Empty,
                  }
                : id === "@plane/ui"
                  ? { Button: ({ children }) => React.createElement("button", null, children) }
                  : id === "@plane/utils"
                    ? {}
                    : id.startsWith("./")
                      ? new Proxy({}, { get: () => Empty })
                      : require(id),
    exports
  );
  return renderToStaticMarkup(
    React.createElement(exports[name], {
      base: "/q/",
      defectId: "d",
      context: {
        is_manager: true,
        user_id: "admin",
        business_roles_enabled: true,
        members: [
          {
            id: "multi",
            name: "兼任同事",
            business_role: "TECHNICIAN",
            business_roles: ["TECHNICIAN", mode === "station" ? "REPORTER" : "PROJECT_MANAGER"],
          },
          { id: "author", name: "方案作者", business_role: "PROJECT_MANAGER", business_roles: ["PROJECT_MANAGER"] },
          { id: "platformadmin", name: "最高管理员", business_role: "PLATFORM_ADMIN", business_roles: ["PLATFORM_ADMIN"] },
        ],
      },
    })
  );
}
test("兼任数采员可选作工作站负责人", () =>
  assert.ok(render("field-resources-panel", "FieldResourcesPanel", "station").includes("兼任同事")));
test("兼任项目经理可选作方案审核人，仍排除作者", () => {
  const html = render("solution-panel", "SolutionPanel", "solution");
  assert.ok(html.includes("兼任同事"));
  assert.ok(!html.includes("方案作者"));
});
test("最高管理员无需兼任即可作为工作站负责人和他人方案审核候选", () => {
  assert.ok(render("field-resources-panel", "FieldResourcesPanel", "station").includes("最高管理员"));
  assert.ok(render("solution-panel", "SolutionPanel", "solution").includes("最高管理员"));
});
