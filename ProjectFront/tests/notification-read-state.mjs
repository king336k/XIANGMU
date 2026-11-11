import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
const code = ts.transpileModule(
  readFileSync(new URL("../core/store/notifications/workspace-notifications.store.ts", import.meta.url), "utf8"),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }
).outputText;
const enums = {
  ENotificationTab: { ALL: "all", MENTIONS: "mentions" },
  ENotificationQueryParamType: { INIT: "init", CURRENT: "current", NEXT: "next" },
  ENotificationLoader: { INIT_LOADER: "init" },
};
function load(service = {}) {
  const api = {};
  new Function("require", "exports", code)((id) => {
    if (id === "mobx") return { makeObservable() {}, observable: {}, action: {}, runInAction: (fn) => fn() };
    if (id === "mobx-utils") return { computedFn: (fn) => fn };
    if (id === "@plane/constants") return enums;
    if (id === "@plane/utils") return { convertToEpoch: Date.parse };
    if (id === "@/services/workspace-notification.service") return { default: service };
    if (id.startsWith("@/")) return {};
    return require(id);
  }, api);
  return new api.WorkspaceNotificationStore({ router: { workspaceSlug: undefined } });
}
test("未读和已读筛选同时用于服务器查询和本地列表，全部包含提及", () => {
  const store = load();
  store.notifications = {
    a: { id: "a", workspace: "w", created_at: "2026-11-01", read_at: null },
    b: { id: "b", workspace: "w", created_at: "2026-11-02", read_at: "2026-11-03", is_mentioned_notification: true },
  };
  for (const [state, param, ids] of [
    ["all", undefined, ["b", "a"]],
    ["unread", false, ["a"]],
    ["read", true, ["b"]],
  ]) {
    store.filters.read_status = state;
    assert.equal(store.generateNotificationQueryParams("init").read, param);
    assert.deepEqual(store.notificationIdsByWorkspaceId("w"), ids);
  }
});
test("通知正文明确显示已读和未读，不只依赖背景颜色", () => {
  const source = readFileSync(
    new URL("../core/components/workspace-notifications/sidebar/notification-card/item.tsx", import.meta.url),
    "utf8"
  );
  assert.match(source, /"已读"/);
  assert.match(source, /"未读"/);
});

test("阅读一条通知只更新该条，接口失败时恢复未读状态和计数", async () => {
  const source = readFileSync(new URL("../core/store/notifications/notification.ts", import.meta.url), "utf8");
  const calls = [],
    counts = [],
    api = {};
  let failing = false;
  const service = {
    markNotificationAsRead: async (workspace, id) => {
      calls.push([workspace, id]);
      if (failing) throw new Error("network");
      return { read_at: "2026-11-09T00:00:00Z" };
    },
  };
  new Function(
    "require",
    "exports",
    ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } })
      .outputText
  )((id) => {
    if (id === "mobx")
      return { makeObservable() {}, observable: {}, computed: {}, action: {}, runInAction: (fn) => fn() };
    if (id === "@/services/workspace-notification.service") return { default: service };
    return require(id);
  }, api);
  const root = { workspaceNotification: { setUnreadNotificationsCount: (value) => counts.push(value) } };
  const first = new api.Notification(root, { id: "first", read_at: null }),
    second = new api.Notification(root, { id: "second", read_at: null });
  await first.markNotificationAsRead("w");
  assert.ok(first.read_at);
  assert.equal(second.read_at, null);
  assert.deepEqual(calls, [["w", "first"]]);
  failing = true;
  await assert.rejects(second.markNotificationAsRead("w"));
  assert.equal(second.read_at, null);
  assert.deepEqual(counts, ["decrement", "decrement", "increment"]);
});

test("快速切换筛选时，旧响应不覆盖新分类和加载状态", async () => {
  let resolve;
  const response = new Promise((done) => {
    resolve = done;
  });
  const store = load({ fetchNotifications: () => response });
  store.getUnreadNotificationsCount = async () => undefined;
  store.mutateNotifications = () => assert.fail("旧响应不应写入当前列表");
  const pending = store.getNotifications("w");
  await Promise.resolve();
  store.filters.read_status = "read";
  store.loader = "new-request";
  resolve({ results: [{ id: "stale" }], total_count: 1 });
  assert.equal(await pending, undefined);
  assert.equal(store.loader, "new-request");
});

test("通知同时显示已读状态与独立业务状态，保留原始事件标题", () => {
  const React = require("react"),
    api = {};
  const Badge = () => null;
  const notification = {
    id: "n",
    project: "p",
    entity_name: "quality",
    read_at: "2026-11-09",
    data: {
      quality: { title: "等待审核的旧通知", url: "/w/projects/p/defects?defect=d" },
      current_record: { kind: "defect", status: "closed", label: "已关闭", available: true },
    },
  };
  const source = readFileSync(
    new URL("../core/components/workspace-notifications/sidebar/notification-card/item.tsx", import.meta.url),
    "utf8"
  );
  new Function(
    "require",
    "exports",
    ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } })
      .outputText
  )((id) => {
    if (id === "react") return { ...React, useState: () => [false, () => {}] };
    if (id === "react/jsx-runtime") return require(id);
    if (id === "mobx-react") return { observer: (fn) => fn };
    if (id === "@/hooks/store/notifications/use-notification")
      return {
        useNotification: () => ({ asJson: notification, markNotificationAsRead: () => assert.fail("渲染不标记已读") }),
      };
    if (id === "@/hooks/store/use-workspace")
      return { useWorkspace: () => ({ getWorkspaceBySlug: () => ({ id: "w" }) }) };
    if (id === "@/components/quality/record-badge") return { Badge };
    if (id === "@plane/utils") return { generateWorkItemLink: () => "/item", calculateTimeAgo: () => "今天" };
    return new Proxy({}, { get: () => () => null });
  }, api);
  function nodes(tree) {
    if (!tree || typeof tree !== "object") return [];
    if (Array.isArray(tree)) return tree.flatMap(nodes);
    return [tree, ...nodes(tree.props?.children)];
  }
  const tree = api.NotificationItem({ workspaceSlug: "w", notificationId: "n" });
  const all = nodes(tree),
    badge = all.find((node) => node.type === Badge);
  assert.equal(badge.props.value, "closed");
  assert.equal(badge.props.label, "缺陷 · 已关闭");
  assert.ok(all.some((node) => node.props?.children === "已读"));
  assert.ok(all.some((node) => node.props?.children === "等待审核的旧通知"));
  const link = all.find((node) => node.props?.to === notification.data.quality.url);
  assert.equal(link.props.children[0].type, "p", "第一行只放通知标题");
  assert.equal(link.props.children[0].props.children, notification.data.quality.title);
  assert.ok(nodes(link.props.children[1]).includes(badge), "业务状态与阅读状态置于第二行");
  assert.equal(badge.props.variant, "plain", "次行状态不使用醒目的胶囊边框底色");
});
