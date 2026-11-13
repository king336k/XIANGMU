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
  Composer = () => null;
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
  const requests = [];
  const data = {
    count: 36,
    participants: [{ id: "u1", name: "项目经理" }],
    results: [{ id: "new", content: "最新", actor: "项目经理" }],
  };
  const api = load("defect-comments.tsx", {
    react: {
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
      default: (key) => {
        requests.push(key);
        return { data: key ? data : undefined, mutate: async () => {}, isLoading: false };
      },
    },
    "./defect-comments-data": helpers,
    "./defect-comments-card": { DefectCommentCard: Card },
    "./defect-comments-editor": { DefectCommentsEditor: Composer },
    "./shared": { Paging: "Paging", Modal: "Modal", fieldClass: "field" },
    "./api": { qualityApi: {}, errorMessage: String },
  });
  return {
    requests,
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
