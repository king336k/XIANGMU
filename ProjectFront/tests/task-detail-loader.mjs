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
    if (id === "@/components/quality/statistics-return-link") {
      const helpers = {};
      const content = readFileSync(
        new URL("../core/components/quality/statistics-return-link.tsx", import.meta.url),
        "utf8"
      );
      new Function(
        "require",
        "exports",
        ts.transpileModule(content, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } })
          .outputText
      )(() => new Proxy({}, { get: () => () => null }), helpers);
      return helpers;
    }
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

test("任务别名跳转保留统计返回筛选、人员和明细页码", async () => {
  const { e } = load();
  const returnTo =
    "/w/analytics?tab=overview&owner_scope=scope&owner_metric=total_work_items&owner_id=person&owner_page=2&owner_status=started&owner_detail_page=2";
  const request = new Request(
    "https://platform.test/w/projects/TASK/issues/i?" + new URLSearchParams({ return_to: returnTo })
  );
  await assert.rejects(
    e.clientLoader({ request, params: { workspaceSlug: "w", projectId: "TASK", issueId: "i" } }),
    (response) => {
      assert.ok(response instanceof Response);
      const destination = new URL(response.headers.get("Location"), "https://platform.test");
      assert.equal(destination.pathname, "/w/browse/TASK-7");
      assert.equal(destination.searchParams.get("return_to"), returnTo);
      return true;
    }
  );
});

test("任务别名跳转不保留站外或其他工作空间返回地址", async () => {
  const { e } = load();
  await Promise.all(
    ["https://evil.test/", "//evil.test/", "/other/analytics"].map(async (returnTo) => {
      const request = new Request(
        "https://platform.test/w/projects/TASK/issues/i?" + new URLSearchParams({ return_to: returnTo })
      );
      await assert.rejects(
        e.clientLoader({ request, params: { workspaceSlug: "w", projectId: "TASK", issueId: "i" } }),
        (response) => response instanceof Response && response.headers.get("Location") === "/w/browse/TASK-7"
      );
    })
  );
});
