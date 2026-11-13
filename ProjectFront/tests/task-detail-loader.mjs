import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
const source = readFileSync(
  new URL(
    "../app/(all)/[workspaceSlug]/(projects)/projects/(detail)/[projectId]/issues/(detail)/[issueId]/page.tsx",
    import.meta.url
  ),
  "utf8"
);
function load() {
  const e = {},
    calls = [];
  new Function(
    "require",
    "exports",
    ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } })
      .outputText
  )((id) => {
    if (id === "next/navigation")
      return {
        useParams: () => {
          throw Error("React hook called outside component");
        },
      };
    if (id === "react-router")
      return { redirect: (path) => new Response(null, { status: 302, headers: { Location: path } }) };
    if (id === "@/services/issue/issue.service")
      return {
        IssueService: class {
          async getIssueMetaFromURL(w, p, i) {
            calls.push([w, p, i]);
            return { project_identifier: "TASK", sequence_id: 7 };
          }
        },
      };
    if (id === "@/services/project/project.service")
      return {
        ProjectService: class {
          async getProjectsLite() {
            return [{ id: "12345678-1234-4234-8234-123456789abc", identifier: "TASK" }];
          }
        },
      };
    return new Proxy({}, { get: () => () => null });
  }, e);
  return { e, calls };
}
test("任务详情loader不用React Hook，项目短编码解析为真实ID后跳转任务", async () => {
  const { e, calls } = load();
  await assert.rejects(
    e.clientLoader({ params: { workspaceSlug: "w", projectId: "TASK", issueId: "i" } }),
    (r) => r instanceof Response && r.status === 302 && r.headers.get("Location") === "/w/browse/TASK-7"
  );
  assert.deepEqual(calls, [["w", "12345678-1234-4234-8234-123456789abc", "i"]]);
});
