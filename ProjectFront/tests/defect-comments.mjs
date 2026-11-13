import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
const nodes = (t) =>
  !t || typeof t !== "object" ? [] : Array.isArray(t) ? t.flatMap(nodes) : [t, ...nodes(t.props?.children)];
const stub = () => null,
  Editor = () => null,
  Button = () => null,
  Card = () => null,
  Composer = () => null,
  Thread = () => null;
function load(file, mocks = {}) {
  const exp = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(`../core/components/quality/${file}`, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((id) => mocks[id] || (id === "react/jsx-runtime" ? require(id) : new Proxy({}, { get: () => stub })), exp);
  return exp;
}
const helpers = load("defect-comments-data.ts");
test("评论检索编码、重试发布意图和附件总量覆盖边界", () => {
  const q = helpers.discussionQuery(2, " 中文 & Topic ", "user");
  assert.equal(q.get("per_page"), "20");
  assert.equal(q.get("page"), "2");
  assert.equal(q.get("search"), "中文 & Topic");
  assert.equal(q.get("author"), "user");
  let seq = 0;
  const body = { content_html: "<p>验证</p>", reply_to: null, attachment_ids: ["f"] };
  const one = helpers.discussionIntent(null, body, () => String(++seq));
  const again = helpers.discussionIntent(one, { ...body }, () => String(++seq));
  assert.equal(one, again);
  assert.equal(seq, 1);
  assert.notEqual(
    helpers.discussionIntent(one, { ...body, reply_to: "reply" }, () => String(++seq)).requestId,
    one.requestId
  );
  assert.throws(
    () =>
      helpers.validateDiscussionFiles(
        Array.from({ length: 10 }, () => ({ size: 1 })),
        [{ name: "a", size: 1 }]
      ),
    /10/
  );
  assert.throws(() => helpers.validateDiscussionFiles([], [{ name: "large", size: 20 * 1024 * 1024 + 1 }]), /20MB/);
  assert.throws(
    () => helpers.validateDiscussionFiles([{ size: 40 * 1024 * 1024 }], [{ name: "sum", size: 11 * 1024 * 1024 }]),
    /50MB/
  );
  assert.doesNotThrow(() => helpers.validateDiscussionFiles([], [{ name: "ok", size: 20 * 1024 * 1024 }]));
});
function editorHarness({
  failFirst = true,
  uuidFactory = () => "12345678-1234-4234-8234-123456789abc",
  intentFactory = helpers.discussionIntent,
  props = {},
} = {}) {
  let cursor = 0,
    rcursor = 0,
    attempt = 0,
    clear = 0;
  const state = [],
    refs = [],
    writes = [],
    inserted = [];
  const api = load("defect-comments-editor.tsx", {
    react: {
      useEffect() {},
      useId: () => "test-editor",
      useState: (v) => {
        const i = cursor++;
        if (!(i in state)) state[i] = v;
        return [state[i], (next) => (state[i] = typeof next === "function" ? next(state[i]) : next)];
      },
      useRef: (v) => {
        const i = rcursor++;
        if (!(i in refs))
          refs[i] = {
            current:
              i === 0
                ? {
                    clearEditor() {
                      clear++;
                    },
                    insertText() {}, // Existing API needs a non-empty selection.
                    setEditorValueAtCursorPosition(value) {
                      inserted.push(value);
                    },
                  }
                : v,
          };
        return refs[i];
      },
    },
    "@plane/editor": { LiteTextEditorWithRef: Editor },
    "@plane/ui": { Button },
    "@plane/utils": { sanitizeHTML: (v) => v.replace(/<[^>]*>/g, "").trim() },
    uuid: { v4: uuidFactory },
    "./defect-comments-data": { ...helpers, discussionIntent: intentFactory },
    "./api": {
      errorMessage: (e) => e.message,
      qualityApi: {
        write: async (url, body) => {
          writes.push([url, body]);
          if (url.endsWith("/files/")) return { id: "file1", name: "记录.txt", size: 4, content_type: "text/plain" };
          if (++attempt === 1 && failFirst) throw Error("网络中断");
          return { id: "comment" };
        },
      },
    },
  });
  return {
    writes,
    inserted,
    get clear() {
      return clear;
    },
    render() {
      cursor = 0;
      rcursor = 0;
      return api.DefectCommentsEditor({
        endpoint: "/q/defects/d/comments/",
        reply: null,
        onCancelReply() {},
        onPublished: async () => {},
        ...props,
      });
    },
  };
}
test("发布失败保留富文本与上传附件，重试沿用同request_id成功后清空", async () => {
  const h = editorHarness();
  let tree = h.render();
  nodes(tree)
    .find((n) => n.type === Editor)
    .props.onChange({}, "<h2>复测</h2><p><strong>成功</strong> 👍</p>");
  const file = new File(["test"], "记录.txt", { type: "text/plain" });
  await nodes(tree)
    .find((n) => n.type === "input" && n.props.type === "file")
    .props.onChange({ target: { files: [file], value: "x" } });
  await new Promise((r) => setTimeout(r, 0));
  tree = h.render();
  const publish = () =>
    nodes(tree)
      .find((n) => n.type === Button)
      .props.onClick();
  await publish();
  tree = h.render();
  assert.equal(h.clear, 0);
  assert.equal(
    nodes(tree).find((n) => n.type === Editor).props.initialValue,
    "<h2>复测</h2><p><strong>成功</strong> 👍</p>"
  );
  assert.ok(nodes(tree).some((n) => n.props?.role === "alert" && n.props.children === "网络中断"));
  await publish();
  tree = h.render();
  const submissions = h.writes.filter(([url]) => !url.endsWith("/files/"));
  assert.equal(submissions.length, 2);
  assert.equal(submissions[0][1].request_id, submissions[1][1].request_id);
  assert.deepEqual(submissions[0][1].attachment_ids, ["file1"]);
  assert.equal(submissions[0][1].content_html, "<h2>复测</h2><p><strong>成功</strong> 👍</p>");
  assert.equal(h.clear, 1);
  assert.ok(!nodes(tree).some((n) => n.props?.children === "记录.txt"));
});
test("输入区按钮不触发外层form，普通Enter不发送，CtrlEnter才提交", () => {
  const tree = editorHarness().render();
  for (const button of nodes(tree).filter((n) => n.type === "button" || n.type === Button))
    assert.equal(button.props.type, "button");
  let prevented = 0;
  tree.props.onKeyDown({
    key: "Enter",
    preventDefault() {
      prevented++;
    },
    stopPropagation() {},
  });
  assert.equal(prevented, 0);
  const editor = nodes(tree).find((n) => n.type === Editor);
  assert.ok(editor.props.disabledExtensions.includes("enter-key"));
  assert.ok(editor.props.disabledExtensions.includes("image"));
});
function panelHarness() {
  let cursor = 0,
    refCursor = 0,
    active = true;
  const state = [],
    refs = [];
  const requests = [],
    refreshed = [];
  const data = {
    count: 36,
    participants: [{ id: "u1", name: "项目经理" }],
    results: [
      { id: "new", content: "最新", actor: "项目经理" },
      { id: "other", content: "其他讨论", actor: "技术员" },
    ],
  };
  const api = load("defect-comments.tsx", {
    react: {
      useEffect() {},
      useId: () => "test-editor",
      useState: (v) => {
        const i = cursor++;
        if (!(i in state)) state[i] = v;
        return [state[i], (next) => (state[i] = next)];
      },
      useRef: (v) => {
        const i = refCursor++;
        if (!(i in refs)) refs[i] = { current: v };
        return refs[i];
      },
    },
    axios: { isAxiosError: (e) => !!e?.isAxiosError },
    swr: {
      useSWRConfig: () => ({
        mutate: async (matcher) => {
          for (const key of [
            "/q/defects/d/comments/?view=threads&page=1",
            "/q/defects/d/comments/root/replies/?page=1",
            "/q/defects/other/comments/root/replies/?page=1",
            "/q/defects/d/comments/files/f/preview/",
          ])
            if (matcher(key)) refreshed.push(key);
        },
      }),
      default: (key) => {
        requests.push(key);
        return { data: key ? data : undefined, mutate: async () => {}, isLoading: false };
      },
    },
    "./defect-comments-data": helpers,
    "./defect-comments-card": { DefectCommentCard: Card },
    "./defect-comments-thread": { DefectCommentThread: Thread },
    "./defect-comments-editor": { DefectCommentsEditor: Composer },
    "./shared": { Paging: "Paging", Modal: "Modal", fieldClass: "field" },
    "./api": { qualityApi: {}, errorMessage: String },
  });
  return {
    requests,
    refreshed,
    set active(v) {
      active = v;
    },
    render() {
      cursor = 0;
      refCursor = 0;
      return api.DefectComments({ base: "/q/", defectId: "d", active });
    },
  };
}
test("评论分页与参与人筛选不卸载输入区；离开页签停止读取", () => {
  const h = panelHarness();
  let tree = h.render();
  const composer = nodes(tree).find((n) => n.type === Composer);
  assert.ok(composer);
  nodes(tree)
    .find((n) => n.type === "Paging")
    .props.onChange(2);
  tree = h.render();
  assert.ok(h.requests.at(-1).includes("page=2"));
  assert.equal(nodes(tree).find((n) => n.type === Composer).key, composer.key);
  nodes(tree)
    .find((n) => n.type === "select")
    .props.onChange({ target: { value: "u1" } });
  tree = h.render();
  assert.ok(h.requests.at(-1).includes("author=u1"));
  assert.ok(h.requests.at(-1).includes("page=1"));
  h.active = false;
  tree = h.render();
  assert.equal(h.requests.at(-1), null);
  assert.ok(nodes(tree).some((n) => n.type === Composer));
});

test("评论卡片保留引用、正文折叠和私有附件地址", () => {
  const { DefectCommentCard } = load("defect-comments-card.tsx", {
    "@plane/utils": { renderNumericDateTime: () => "2026/11/13 10:00" },
    "./defect-comments-data": helpers,
  });
  const comment = {
    id: "c",
    actor: "测试员",
    created_by_id: "u",
    created_at: "2026-11-13T02:00:00Z",
    content: "长讨论".repeat(500),
    content_html: "<p><strong>复测</strong> ✅</p>",
    reply_to: { id: "before", actor: "技术员", content: "修复说明" },
    attachments: [
      { id: "image1", name: "现场.png", size: 5, content_type: "image/png" },
      { id: "file1", name: "日志.txt", size: 4, content_type: "text/plain" },
    ],
  };
  let replied, downloaded, previewed;
  const tree = DefectCommentCard({
    comment,
    endpoint: "/q/defects/d/comments/",
    onReply: (value) => {
      replied = value;
    },
    onDownload: (value) => {
      downloaded = value;
    },
    onPreview: (value) => {
      previewed = value;
    },
  });
  assert.ok(nodes(tree).some((n) => n.type === "details" && !n.props.open));
  assert.ok(nodes(tree).some((n) => n.type === "blockquote"));
  assert.ok(nodes(tree).some((n) => n.type === "img" && n.props.src === "/q/defects/d/comments/files/image1/preview/"));
  nodes(tree)
    .find((n) => n.type === "button" && n.props["aria-label"] === "下载 日志.txt")
    .props.onClick();
  assert.equal(downloaded.id, "file1");
  nodes(tree)
    .find((n) => n.type === "button" && n.props["aria-label"] === "预览 现场.png")
    .props.onClick();
  assert.equal(previewed.id, "image1");
  nodes(tree)
    .find((n) => n.type === "button" && Array.isArray(n.props.children) && n.props.children.includes("回复"))
    .props.onClick();
  assert.equal(replied.id, "c");
});

test("评论页签位于回归与操作记录之间，内容全宽且不显示缺陷属性", () => {
  let index = 0;
  const { DefectDetail } = load("defect-detail.tsx", {
    react: { useState: (value) => [index++ === 2 ? "comments" : value, () => {}] },
    "./shared": { Modal: "Modal", Badge: "Badge" },
    "./types": { can: () => false, severityNames: {} },
    "./defect-disposition": { resolutionNames: {} },
    "./defect-comments": { DefectComments: "Discussion" },
  });
  const tree = DefectDetail({
    base: "/q/",
    value: { id: "d", code: "D-1", title: "问题", status: "open" },
    context: { user_id: "u", members: [] },
    projectUrl: "/p/",
    onClose() {},
    onEdit() {},
    onChanged: async () => {},
  });
  const tabs = nodes(tree)
    .filter((n) => n.type === "button" && n.props.role === "tab")
    .map((n) => n.props.children);
  assert.deepEqual(tabs.slice(-3), ["回归测试", "评论", "操作记录"]);
  assert.ok(!nodes(tree).some((n) => n.type === "aside"));
  assert.ok(nodes(tree).some((n) => n.type === "div" && n.props.className === "defect-page-regression"));
  const discussion = nodes(tree).find((n) => n.type === "Discussion");
  assert.equal(discussion.props.active, true);
  assert.equal(discussion.key, "d:u");
});

test("表情在没有文字选区的当前光标处插入", () => {
  const h = editorHarness();
  let tree = h.render();
  nodes(tree)
    .find((n) => n.type === "button" && n.props["aria-label"] === "添加表情")
    .props.onClick();
  tree = h.render();
  nodes(tree)
    .find((n) => n.type === "button" && n.props["aria-label"] === "插入 👍")
    .props.onClick();
  assert.deepEqual(h.inserted, ["👍"]);
  tree = h.render();
  assert.ok(!nodes(tree).some((n) => n.type === "button" && n.props["aria-label"] === "插入 👍"));
});

test("HTTP环境无crypto.randomUUID仍可发布评论并解除busy", async () => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "crypto");
  Object.defineProperty(globalThis, "crypto", { configurable: true, value: { randomUUID: undefined } });
  try {
    const h = editorHarness({ failFirst: false });
    let tree = h.render();
    nodes(tree)
      .find((n) => n.type === Editor)
      .props.onChange({}, "<p>HTTP评论</p>");
    tree = h.render();
    await nodes(tree)
      .find((n) => n.type === Button)
      .props.onClick();
    await new Promise((r) => setTimeout(r, 0));
    tree = h.render();
    assert.equal(h.writes.length, 1);
    assert.equal(h.writes[0][1].request_id, "12345678-1234-4234-8234-123456789abc");
    assert.equal(h.clear, 1);
    assert.equal(nodes(tree).find((n) => n.type === Button).props.children, "发布评论");
  } finally {
    if (descriptor) Object.defineProperty(globalThis, "crypto", descriptor);
    else delete globalThis.crypto;
  }
});
test("编号生成异常保留草稿并解除busy，展示错误后可重试", async () => {
  const h = editorHarness({
    failFirst: false,
    intentFactory: () => {
      throw Error("编号生成失败");
    },
  });
  let tree = h.render();
  nodes(tree)
    .find((n) => n.type === Editor)
    .props.onChange({}, "<p>不能丢失的草稿</p>");
  tree = h.render();
  await nodes(tree)
    .find((n) => n.type === Button)
    .props.onClick();
  await new Promise((r) => setTimeout(r, 0));
  tree = h.render();
  assert.equal(h.writes.length, 0);
  assert.equal(h.clear, 0);
  assert.equal(nodes(tree).find((n) => n.type === Editor).props.initialValue, "<p>不能丢失的草稿</p>");
  assert.equal(nodes(tree).find((n) => n.type === Button).props.children, "发布评论");
  assert.equal(nodes(tree).find((n) => n.type === Button).props.disabled, false);
  assert.ok(nodes(tree).some((n) => n.props?.role === "alert" && n.props.children === "编号生成失败"));
});

test("同一评论连续回复保留引用对象，发布成功后只清输入不退出回复", async () => {
  let cancelled = 0,
    published = 0;
  const target = { id: "root", actor: "技术员", content: "修复说明" };
  const h = editorHarness({
    failFirst: false,
    props: {
      reply: target,
      preserveReplyAfterPublish: true,
      onCancelReply() {
        cancelled++;
      },
      onPublished: async () => {
        published++;
      },
    },
  });
  let tree = h.render();
  nodes(tree)
    .find((n) => n.type === Editor)
    .props.onChange({}, "<p>第一次回复</p>");
  tree = h.render();
  await nodes(tree)
    .find((n) => n.type === Button)
    .props.onClick();
  tree = h.render();
  assert.equal(cancelled, 0);
  assert.equal(published, 1);
  assert.equal(h.clear, 1);
  assert.ok(nodes(tree).some((n) => n.type === "p" && n.props.children?.includes?.("技术员")));
  nodes(tree)
    .find((n) => n.type === Editor)
    .props.onChange({}, "<p>第二次回复</p>");
  tree = h.render();
  await nodes(tree)
    .find((n) => n.type === Button)
    .props.onClick();
  assert.equal(h.writes.length, 2);
  assert.ok(h.writes.every(([, body]) => body.reply_to === "root"));
  assert.notEqual(h.writes[0][1].content_html, h.writes[1][1].content_html);
  assert.equal(cancelled, 0);
});

test("主评论请求使用线程视图，未展开回复不读取回复接口", () => {
  const h = panelHarness();
  h.render();
  assert.equal(new URL(h.requests[0], "https://test").searchParams.get("view"), "threads");
});

function threadHarness() {
  let cursor = 0,
    selected = null,
    active = true,
    search = "",
    author = "",
    root = { id: "root", actor: "经理", content: "主讨论", reply_count: 25 };
  const state = [],
    requests = [],
    draft = { current: { html: "<p>保留草稿</p>", files: [{ id: "f", name: "图.png", size: 1 }], intent: null } };
  const { DefectCommentThread } = load("defect-comments-thread.tsx", {
    react: {
      useRef: (v) => ({ current: v }),
      useEffect() {},
      useId: () => "test-editor",
      useState: (v) => {
        const i = cursor++;
        if (!(i in state)) state[i] = v;
        return [state[i], (next) => (state[i] = typeof next === "function" ? next(state[i]) : next)];
      },
    },
    swr: {
      default: (key) => {
        requests.push(key);
        return {
          data: key
            ? {
                count: 25,
                reply_count: 25,
                thread_id: "root",
                results: [{ id: "child", actor: "技术员", content: "子回复", thread_id: "root" }],
              }
            : undefined,
          mutate: async () => {},
        };
      },
    },
    "./defect-comments-card": { DefectCommentCard: Card },
    "./defect-comments-editor": { DefectCommentsEditor: Composer },
    "./shared": { Paging: "Paging" },
    "./api": { qualityApi: {}, errorMessage: String },
  });
  return {
    requests,
    draft,
    set active(value) {
      active = value;
    },
    get selected() {
      return selected;
    },
    set selected(value) {
      selected = value;
    },
    render() {
      cursor = 0;
      return DefectCommentThread({
        comment: root,
        endpoint: "/q/defects/d/comments/",
        active,
        search,
        author,
        reply: selected,
        draftStore: draft,
        onReply: (rootId, target) => {
          assert.equal(rootId, "root");
          selected = target;
        },
        onCancelReply: () => {
          selected = null;
        },
        onRefresh: async () => {},
        onPreview() {},
        onDownload() {},
      });
    },
  };
}
test("线程默认折叠不读取回复，展开按10条分页，连续回复不改变目标", async () => {
  const h = threadHarness();
  let tree = h.render();
  assert.equal(h.requests[0], null);
  assert.ok(!nodes(tree).some((n) => n.type === Composer));
  nodes(tree)
    .find((n) => n.type === "button" && n.props["aria-expanded"] === false)
    .props.onClick();
  tree = h.render();
  assert.match(h.requests.at(-1), /root\/replies\//);
  assert.equal(new URL(h.requests.at(-1), "https://test").searchParams.get("per_page"), "10");
  nodes(tree)
    .find((n) => n.type === Card && n.props.comment.id === "child")
    .props.onReply({ id: "child", actor: "技术员", content: "子回复", thread_id: "root" });
  tree = h.render();
  const composer = nodes(tree).find((n) => n.type === Composer);
  assert.equal(composer.props.reply.id, "child");
  assert.equal(composer.props.preserveReplyAfterPublish, true);
  assert.equal(composer.props.draftStore, h.draft);
  const anchor = nodes(tree).find((n) => n.type === "div" && n.props["aria-label"] === "回复输入区");
  assert.ok(anchor?.props?.ref || anchor?.ref, "回复输入器必须挂载滚动和聚焦目标");
  nodes(tree)
    .find((n) => n.type === "Paging")
    .props.onChange(2);
  tree = h.render();
  assert.equal(new URL(h.requests.at(-1), "https://test").searchParams.get("page"), "2");
  await composer.props.onPublished();
  tree = h.render();
  assert.equal(new URL(h.requests.at(-1), "https://test").searchParams.get("page"), "1");
  assert.equal(h.selected.id, "child");
  nodes(tree)
    .find((n) => n.type === "button" && n.props["aria-expanded"] === true)
    .props.onClick();
  tree = h.render();
  assert.equal(h.requests.at(-1), null);
  assert.ok(nodes(tree).some((n) => n.type === Composer));
  assert.equal(h.draft.current.files[0].id, "f");
});

test("不同讨论使用独立回复草稿，筛选分页重渲染保留各自附件", () => {
  const h = panelHarness();
  let tree = h.render();
  let threads = nodes(tree).filter((n) => n.type === Thread);
  assert.equal(threads.length, 2);
  assert.notEqual(threads[0].props.draftStore, threads[1].props.draftStore);
  const first = threads[0].props.draftStore;
  first.current = { html: "<p>A草稿</p>", files: [{ id: "a-file" }], intent: null };
  threads[0].props.onReply("new", { id: "child-a", actor: "经理", content: "引用A" });
  tree = h.render();
  threads = nodes(tree).filter((n) => n.type === Thread);
  assert.equal(threads[0].props.reply.id, "child-a");
  assert.equal(threads[0].props.draftStore, first);
  threads[1].props.onReply("other", { id: "other", actor: "技术员", content: "B" });
  tree = h.render();
  threads = nodes(tree).filter((n) => n.type === Thread);
  assert.equal(threads[0].props.reply, null);
  assert.equal(threads[1].props.reply.id, "other");
  assert.equal(threads[1].props.draftStore.current.html, "");
  assert.equal(threads[0].props.draftStore.current.files[0].id, "a-file");
});

test("刷新评论同时刷新本缺陷主讨论和已缓存回复，不触碰其他缺陷或附件", async () => {
  const h = panelHarness();
  const tree = h.render();
  await nodes(tree)
    .find((n) => n.type === "button" && n.props["aria-label"] === "刷新评论")
    .props.onClick();
  assert.deepEqual(h.refreshed, [
    "/q/defects/d/comments/?view=threads&page=1",
    "/q/defects/d/comments/root/replies/?page=1",
  ]);
});
