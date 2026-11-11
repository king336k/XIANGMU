import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
function navigation() {
  const code = ts.transpileModule(
    readFileSync(new URL("../core/components/navigation/notification-navigation.ts", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }
  ).outputText;
  const exports = {};
  new Function("exports", code)(exports);
  return exports.notificationNavigation;
}
test("通知入口保存原页面的筛选、分页和锚点，第二次点击返回同一页面", () => {
  const get = navigation();
  const from = { pathname: "/work/projects/project/defects/", search: "?status=open&page=3", hash: "#files" };
  const opened = get("work", from);
  assert.equal(opened.to, "/work/notifications/");
  const returned = get("work", { pathname: opened.to, search: "?filter=all", hash: "", state: opened.state });
  assert.equal(returned.to, "/work/projects/project/defects/?status=open&page=3#files");
  assert.equal(returned.label, "返回原页面");
  assert.equal(returned.isInbox, true);
});
test("直接进入通知页时返回项目目录，拒绝外站、其他空间和循环地址", () => {
  const get = navigation();
  for (const returnTo of [
    undefined,
    "https://example.com/",
    "//example.com/",
    "/other/projects/",
    "/work/notifications/",
    "/work/%2e%2e/other/",
    "/work/\\example.com",
  ]) {
    assert.equal(
      get("work", { pathname: "/work/notifications/", search: "", hash: "", state: { notificationReturnTo: returnTo } })
        .to,
      "/work/projects/"
    );
  }
});
test("通知页不带末尾斜杠时也能返回，普通项目路径不被误判", () => {
  const get = navigation();
  assert.equal(
    get("work", {
      pathname: "/work/notifications",
      search: "",
      hash: "",
      state: { notificationReturnTo: "/work/projects/p/quality?tab=cases" },
    }).to,
    "/work/projects/p/quality?tab=cases"
  );
  assert.equal(get("work", { pathname: "/work/projects/notifications/issues/", search: "", hash: "" }).isInbox, false);
});
