import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("周期与模块详情为侧栏保留空间且窄屏可独立查看", () => {
  for (const [section, entity] of [
    ["cycles", "cycle"],
    ["modules", "module"],
  ]) {
    const path = `../app/(all)/[workspaceSlug]/(projects)/projects/(detail)/[projectId]/${section}/(detail)/[${entity}Id]/page.tsx`;
    const source = readFileSync(new URL(path, import.meta.url), "utf8");
    assert.ok(source.includes("<aside") && source.includes("aria-label="));
    assert.ok(source.includes("min-w-0 flex-1 overflow-hidden"));
    assert.ok(source.includes('"hidden xl:block"'));
    const panel = source.match(/<aside[\s\S]*?<\/aside>/)?.[0];
    assert.ok(panel && !panel.includes("absolute right-0"));
    assert.ok(panel.includes("min-h-0") && panel.includes("overflow-y-auto") && panel.includes("w-full"));
  }
});

test("共用布局可缩放，移动端收起侧栏采用幂等设置", () => {
  const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
  assert.match(read("../app/(all)/[workspaceSlug]/(projects)/layout.tsx"), /min-h-0 min-w-0 flex-1/);
  assert.match(read("../core/components/core/content-wrapper.tsx"), /min-h-0 w-full min-w-0 flex-1/);
  assert.match(read("../core/components/common/extended-app-header.tsx"), /min-w-0 flex-1/);
  const sidebar = read("../core/components/sidebar/sidebar-wrapper.tsx");
  assert.ok(!sidebar.includes("toggleSidebar();"));
  assert.equal(sidebar.match(/toggleSidebar\(true\)/g)?.length, 2);
});
