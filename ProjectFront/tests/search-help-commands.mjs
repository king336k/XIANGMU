import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const code = ts.transpileModule(
  readFileSync(new URL("../core/components/power-k/config/help-commands.ts", import.meta.url), "utf8"),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }
).outputText;
test("搜索帮助只进入平台帮助、快捷键和当前项目缺陷，移除论坛和上游GitHub", () => {
  const exports = {},
    routes = [],
    events = [];
  new Function("require", "exports", "window", "Event", code)(
    (id) => {
      if (id === "@/hooks/use-resolved-project-params")
        return { useResolvedProjectParams: () => ({ workspaceSlug: "work", projectId: "project" }) };
      if (id === "react-router")
        return {
          useParams: () => ({ workspaceSlug: "work", projectId: "project" }),
          useNavigate: () => (value) => routes.push(value),
        };
      if (id === "@/hooks/store/use-power-k") return { usePowerK: () => ({ toggleShortcutsListModal() {} }) };
      return require(id);
    },
    exports,
    {
      dispatchEvent: (event) => events.push(event.type),
      open: () => {
        throw new Error("Unexpected external navigation");
      },
    },
    function SyntheticEvent(type) {
      this.type = type;
    }
  );
  const commands = exports.usePowerKHelpCommands();
  assert.ok(!commands.some((row) => row.id === "join_forum"));
  commands.find((row) => row.id === "open_plane_documentation").action();
  assert.deepEqual(events, ["platform-help-open"]);
  commands.find((row) => row.id === "report_bug").action();
  assert.deepEqual(routes, ["/work/projects/project/defects/?create=1"]);
});
