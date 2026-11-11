import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
const source = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
test("通知使用整页列表，原生工作项直接跳详情，不保留预览空栏", () => {
  const layout = source("app/(all)/[workspaceSlug]/(projects)/notifications/layout.tsx");
  const root = source("core/components/workspace-notifications/root.tsx");
  const item = source("core/components/workspace-notifications/sidebar/notification-card/item.tsx");
  assert.doesNotMatch(layout, /NotificationsSidebarRoot/);
  assert.match(root, /NotificationsSidebarRoot/);
  assert.doesNotMatch(root, /PeekOverviewComponent|EmptyStateCompact|InboxContentRoot/);
  assert.doesNotMatch(item, /setPeekIssue|setCurrentSelectedNotificationId|handleNotificationIssuePeekOverview/);
  assert.match(item, /generateWorkItemLink/);
  assert.match(item, /to={nativeHref}/);
});
test("通知列表不被固定四分之一宽度限制，标题与操作不互相遮挡", () => {
  assert.doesNotMatch(source("core/components/workspace-notifications/sidebar/root.tsx"), /md:w-3\/12|"w-0/);
  assert.doesNotMatch(
    source("core/components/workspace-notifications/sidebar/header/root.tsx"),
    /Breadcrumbs|Header.LeftItem/
  );
});
