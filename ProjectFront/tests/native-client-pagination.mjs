import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
function load(path, mocks = {}) {
  const api = {};
  const code = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  new Function("require", "exports", code)(
    (id) => mocks[id] ?? (id === "react/jsx-runtime" ? require(id) : new Proxy({}, { get: () => () => null })),
    api
  );
  return api;
}
const values = (count) => Array.from({ length: count }, (_, i) => i + 1);
test("完整结果集分页支持20/50/100并在删除后夹紧尾页", () => {
  const { nativePageWindow, NATIVE_PAGE_SIZES } = load("../core/components/common/native-client-pagination.tsx");
  assert.deepEqual(NATIVE_PAGE_SIZES, [20, 50, 100]);
  for (const size of NATIVE_PAGE_SIZES) {
    const page = nativePageWindow(values(125), 3, size);
    assert.deepEqual(page.items, values(125).slice((page.page - 1) * size, page.page * size));
  }
  assert.equal(nativePageWindow(values(21), 4, 20).page, 2);
  assert.deepEqual(nativePageWindow(values(0), 4, 20).items, []);
});

test("筛选和排序后分页，改变筛选/条数回到第一页，删除夹紧且保留条数", () => {
  const React = require("react");
  let state;
  const { useNativeClientPagination } = load("../core/components/common/native-client-pagination.tsx", {
    react: {
      ...React,
      useState: (initial) => [
        state ?? initial,
        (next) => {
          state = next;
        },
      ],
    },
    "next/navigation": { usePathname: () => "/w/projects" },
  });
  const filtered = values(160)
      .filter((value) => value % 2 === 0)
      .reverse(),
    copy = [...filtered];
  let result = useNativeClientPagination(filtered, "search=even&sort=desc");
  assert.deepEqual(result.items, filtered.slice(0, 20));
  result.onChange(3);
  result = useNativeClientPagination(filtered, "search=even&sort=desc");
  assert.deepEqual(result.items, filtered.slice(40, 60));
  result.onPageSizeChange(50);
  result = useNativeClientPagination(filtered, "search=even&sort=desc");
  assert.equal(result.page, 1);
  assert.equal(result.items.length, 50);
  result.onChange(2);
  result = useNativeClientPagination(filtered.slice(0, 12), "search=even&sort=desc");
  assert.equal(result.page, 1);
  assert.equal(result.count, 12);
  assert.equal(result.perPage, 50);
  result = useNativeClientPagination(filtered, "search=other&sort=desc");
  assert.equal(result.page, 1);
  assert.equal(result.perPage, 50);
  assert.deepEqual(filtered, copy);
});
test("项目列表分页接收已筛选排序结果，分页不会改动筛选条件", () => {
  const React = require("react"),
    received = [];
  const { ProjectCardList } = load("../core/components/project/card-list.tsx", {
    "mobx-react": { observer: (fn) => fn },
    "@plane/i18n": { useTranslation: () => ({ t: (key) => key }) },
    "@plane/constants": { EUserPermissions: { ADMIN: 1, MEMBER: 2 }, EUserPermissionsLevel: { WORKSPACE: 1 } },
    "@/hooks/store/use-command-palette": { useCommandPalette: () => ({}) },
    "@/hooks/store/use-project": {
      useProject: () => ({
        loader: undefined,
        fetchStatus: "complete",
        workspaceProjectIds: values(80),
        filteredProjectIds: values(60).reverse(),
        getProjectById: (id) => ({ id }),
      }),
    },
    "@/hooks/store/use-project-filter": {
      useProjectFilter: () => ({
        searchQuery: "test",
        currentWorkspaceFilters: { priority: ["high"] },
        currentWorkspaceDisplayFilters: { sort_by: "name" },
      }),
    },
    "@/hooks/store/user": { useUserPermissions: () => ({ allowPermissions: () => false }) },
    "@/components/common/native-client-pagination": {
      useNativeClientPagination: (items, scope) => {
        received.push({ items, scope });
        return { items: items.slice(20, 40), page: 2, count: items.length, perPage: 20 };
      },
      NativeClientPagination: () => null,
    },
  });
  const tree = ProjectCardList({});
  assert.deepEqual(received[0].items, values(60).reverse());
  assert.match(received[0].scope, /test/);
  assert.match(received[0].scope, /sort_by/);
  assert.equal(tree.props.children[0].props.children.length, 20);
  assert.equal(tree.props.children[1].props.pagination.count, 60);
});
test("工作区成员先按活跃状态排序，邀请使用独立分页且完整计数保留", () => {
  const React = require("react"),
    received = [];
  const members = values(55).map((id) => `member-${id}`),
    invites = values(35).map((id) => `invite-${id}`);
  const { WorkspaceMembersList } = load("../core/components/workspace/settings/members-list.tsx", {
    react: { ...React, useState: (initial) => [initial, () => {}] },
    "mobx-react": { observer: (fn) => fn },
    "next/navigation": { useParams: () => ({ workspaceSlug: "w" }) },
    swr: { default: () => ({}) },
    "@plane/i18n": { useTranslation: () => ({ t: (key) => key }) },
    "@headlessui/react": { Disclosure: { Panel: () => null } },
    "@/hooks/store/use-member": {
      useMember: () => ({
        workspace: {
          fetchWorkspaceMembers() {},
          fetchWorkspaceMemberInvitations() {},
          workspaceMemberIds: members,
          workspaceMemberInvitationIds: invites,
          getFilteredWorkspaceMemberIds: () => members,
          getSearchedWorkspaceInvitationIds: () => invites,
          getWorkspaceMemberDetails: (id) => ({ id, is_active: Number(id.split("-")[1]) % 2 === 0 }),
          filtersStore: { filters: { roles: [10] } },
        },
      }),
    },
    "@/components/common/native-client-pagination": {
      useNativeClientPagination: (items, scope) => {
        received.push({ items, scope });
        return { items: items.slice(0, 20), page: 1, count: items.length, perPage: 20 };
      },
      NativeClientPagination: () => null,
    },
  });
  const tree = WorkspaceMembersList({ searchQuery: "", isAdmin: true });
  assert.equal(received.length, 2);
  assert.ok(received[0].items.slice(0, 20).every((x) => x.is_active));
  assert.deepEqual(received[1].items, invites);
  assert.equal(tree.props.children[1].props.pagination.count, 55);
  const collapsible = tree.props.children[2];
  assert.equal(collapsible.props.children.props.children[1].props.pagination.count, 35);
});
test("最近访问把所选条数传给服务端，分页总数使用count", () => {
  const React = require("react"),
    requests = [];
  let stateCall = 0;
  class Service {
    fetchWorkspaceRecentPage(...args) {
      requests.push(args);
      return Promise.resolve({ count: 321, results: [] });
    }
  }
  const { RecentActivityWidget } = load("../core/components/home/widgets/recents/index.tsx", {
    react: {
      ...React,
      useState: () => [["issue", 2, 50][stateCall++], () => {}],
      useEffect() {},
      useRef: () => ({ current: null }),
    },
    "mobx-react": { observer: (fn) => fn },
    "@plane/i18n": { useTranslation: () => ({ t: (key) => key }) },
    swr: {
      default: (_key, fetcher) => {
        fetcher();
        return { data: { count: 321, results: [] }, isLoading: false };
      },
    },
    "@/services/workspace.service": { WorkspaceService: Service },
    "../loaders": { EWidgetKeys: { RECENT_ACTIVITY: "recent" } },
    "@/components/common/native-client-pagination": { NATIVE_PAGE_SIZES: [20, 50, 100] },
  });
  const tree = RecentActivityWidget({ workspaceSlug: "w" });
  assert.deepEqual(requests, [["w", "issue", 2, 50]]);
  const footer = tree.props.children[3];
  assert.equal(footer.props.count, 321);
  assert.equal(footer.props.perPage, 50);
  assert.deepEqual(footer.props.pageSizes, [10, 20, 50]);
});

test("项目成员搜索角色筛选之后分页，权限与邀请入口保留", () => {
  const React = require("react"),
    received = [];
  const { ProjectMemberList } = load("../core/components/project/member-list.tsx", {
    react: { ...React, useState: (initial) => [initial, () => {}] },
    "mobx-react": { observer: (fn) => fn },
    "@plane/i18n": { useTranslation: () => ({ t: (key) => key }) },
    "@plane/constants": {
      EUserPermissions: { ADMIN: 20 },
      EUserPermissionsLevel: { PROJECT: 1 },
      MEMBER_TRACKER_ELEMENTS: {},
    },
    "@/hooks/store/user": { useUserPermissions: () => ({ allowPermissions: () => false }) },
    "@/hooks/store/use-member": {
      useMember: () => ({
        project: {
          projectMemberIds: values(45),
          getFilteredProjectMemberDetails: (id) => ({
            member: { first_name: `member${id}`, last_name: "test", display_name: `member${id}` },
            original_role: 10,
          }),
          filters: { getFilters: () => ({ roles: ["10"] }) },
        },
      }),
    },
    "@/components/common/native-client-pagination": {
      useNativeClientPagination: (items, scope) => {
        received.push({ items, scope });
        return { items: items.slice(20, 40), page: 2, count: items.length, perPage: 20 };
      },
      NativeClientPagination: () => null,
    },
  });
  const tree = ProjectMemberList({ projectId: "p", workspaceSlug: "w" });
  assert.equal(received[0].items.length, 45);
  assert.match(received[0].scope, /"10"/);
  assert.equal(tree.props.children[2].props.children[0].props.memberDetails.length, 20);
  assert.equal(tree.props.children[3].props.pagination.count, 45);
});
test("项目视图与工作区视图都对现有搜索结果分页", () => {
  const React = require("react"),
    received = [];
  const pagers = {
    useNativeClientPagination: (items, scope) => {
      received.push({ items, scope });
      return { items: items.slice(20, 40), page: 2, count: items.length, perPage: 20 };
    },
    NativeClientPagination: () => null,
  };
  const common = {
    "mobx-react": { observer: (fn) => fn },
    "next/navigation": { useParams: () => ({ projectId: "p", workspaceSlug: "w" }) },
    "@/components/common/native-client-pagination": pagers,
  };
  const viewItems = values(50)
    .map((id) => ({ id }))
    .reverse();
  const { ProjectViewsList } = load("../core/components/views/views-list.tsx", {
    ...common,
    "@plane/i18n": { useTranslation: () => ({ t: (key) => key }) },
    "@plane/constants": { EUserPermissionsLevel: { PROJECT: 1 } },
    "@plane/types": { EUserProjectRoles: {} },
    "@/hooks/store/use-command-palette": { useCommandPalette: () => ({}) },
    "@/hooks/store/use-project-view": {
      useProjectView: () => ({
        getProjectViews: () => viewItems,
        getFilteredProjectViews: () => viewItems,
        filters: { searchQuery: "abc", sortBy: "desc" },
      }),
    },
    "@/hooks/store/user": { useUserPermissions: () => ({ allowPermissions: () => false }) },
  });
  const project = ProjectViewsList();
  assert.deepEqual(received[0].items, viewItems);
  assert.match(received[0].scope, /abc/);
  assert.equal(project.props.children.props.children[0].props.children.length, 20);
  const { GlobalViewsList } = load("../core/components/workspace/views/views-list.tsx", {
    ...common,
    swr: { default: () => ({}) },
    "@/hooks/store/use-global-view": {
      useGlobalView: () => ({
        fetchAllGlobalViews() {},
        currentWorkspaceViews: values(55),
        getSearchedViews: (query) => (query === "abc" ? values(35) : []),
      }),
    },
  });
  const global = GlobalViewsList({ searchQuery: "abc" });
  assert.deepEqual(received[1].items, values(35));
  assert.equal(global.props.children[0].length, 15);
  assert.equal(global.props.children[1].props.pagination.count, 35);
});
