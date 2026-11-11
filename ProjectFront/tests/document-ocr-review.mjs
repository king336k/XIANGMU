import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const React = require("react");
const stubs = new Map();
const stub = (name) => {
  if (!stubs.has(name)) stubs.set(name, ({ children }) => React.createElement("div", null, children));
  return stubs.get(name);
};
function harness(file, api = {}) {
  let cursor = 0;
  const state = [],
    effects = [],
    refs = [],
    timers = new Map();
  let timerId = 0;
  const exports = {};
  const code = ts.transpileModule(
    readFileSync(new URL(`../core/components/quality/${file}.tsx`, import.meta.url), "utf8"),
    {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }
  ).outputText;
  new Function("require", "exports", "setTimeout", "clearTimeout", code)(
    (id) => {
      if (id === "react")
        return {
          ...React,
          useState(value) {
            const at = cursor++;
            if (!(at in state)) state[at] = typeof value === "function" ? value() : value;
            return [
              state[at],
              (next) => {
                state[at] = typeof next === "function" ? next(state[at]) : next;
              },
            ];
          },
          useRef(value) {
            const at = cursor++;
            return (refs[at] ||= { current: value });
          },
          useEffect(fn, deps) {
            const at = cursor++;
            const old = effects[at];
            if (!old || deps.some((dep, i) => !Object.is(dep, old.deps[i]))) {
              old?.cleanup?.();
              effects[at] = { deps, cleanup: fn() };
            }
          },
        };
      if (id === "react/jsx-runtime") return require(id);
      if (id === "./api") return { qualityApi: api, errorMessage: (e) => e.message || "失败" };
      return new Proxy({}, { get: (_, name) => (name === "fieldClass" ? "field" : stub(String(name))) });
    },
    exports,
    (fn, ms) => {
      const id = ++timerId;
      timers.set(id, { fn, ms });
      return id;
    },
    (id) => timers.delete(id)
  );
  return {
    exports,
    state,
    timers,
    render(name, props) {
      cursor = 0;
      return exports[name](props);
    },
    unmount() {
      effects.forEach((effect) => effect?.cleanup?.());
    },
  };
}
function nodes(tree) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
const text = (tree) =>
  nodes(tree)
    .flatMap((node) => (Array.isArray(node.props?.children) ? node.props.children : [node.props?.children]))
    .filter((x) => typeof x === "string")
    .join(" ");
const button = (tree, label) =>
  nodes(tree).find((node) => node.type === stub("Button") && node.props.children === label);
const complete = {
  token: "t1",
  status: "completed",
  requires_review: true,
  segments: [{ key: "ocr-1", page: 2, text: "原始候选错字" }],
  failures: [],
};
const preview = {
  id: "i1",
  valid: true,
  rows: [{ title: "原稿", content: "原预检正文" }],
  files: [],
  errors: [],
  status: "preview",
  extraction: {},
};
const props = (initial = complete, extra = {}) => ({
  base: "/q/",
  importId: "i1",
  initial,
  onPendingChange() {},
  onApplied() {},
  ...extra,
});
test("OCR候选以可编辑文字和页码展示，未勾核对不能采用", () => {
  const h = harness("document-ocr-review");
  const tree = h.render("DocumentOcrReview", props());
  assert.match(text(tree), /第2页/);
  assert.equal(nodes(tree).find((n) => n.type === "textarea").props.value, "原始候选错字");
  assert.equal(button(tree, "采用核对结果").props.disabled, true);
});
test("人工修订并勾选后仅发送key/text和当前token，返回预检由外层采用", async () => {
  const writes = [],
    applied = [],
    pending = [];
  const next = { ...preview, extraction: { ocr: { ...complete, reviewed: true, requires_review: false } } };
  const h = harness("document-ocr-review", {
    write: async (...args) => {
      writes.push(args);
      return next;
    },
  });
  const p = props(complete, {
    onApplied: (value) => applied.push(value),
    onPendingChange: (value) => pending.push(value),
  });
  let tree = h.render("DocumentOcrReview", p);
  nodes(tree)
    .find((n) => n.type === "textarea")
    .props.onChange({ target: { value: "已对照原图修正" } });
  tree = h.render("DocumentOcrReview", p);
  nodes(tree)
    .find((n) => n.type === "input" && n.props.type === "checkbox")
    .props.onChange({ target: { checked: true } });
  tree = h.render("DocumentOcrReview", p);
  assert.equal(button(tree, "采用核对结果").props.disabled, false);
  await button(tree, "采用核对结果").props.onClick();
  assert.deepEqual(writes, [
    [
      "/q/document-imports/i1/ocr/review/",
      { expected_token: "t1", confirmed: true, segments: [{ key: "ocr-1", text: "已对照原图修正" }] },
    ],
  ]);
  assert.deepEqual(applied, [next]);
  assert.equal(pending.at(-1), false);
});
test("任一失败范围显示真实位置且不能采用成功片段", () => {
  const h = harness("document-ocr-review");
  const tree = h.render("DocumentOcrReview", props({ ...complete, failures: [{ page: 3, error: "没有可识别文字" }] }));
  assert.match(text(tree), /第3页.*没有可识别文字/);
  assert.ok(!button(tree, "采用核对结果") || button(tree, "采用核对结果").props.disabled);
});
test("queued/running每2秒查询，关闭清理timer并忽略已在途结果", async () => {
  let resolve,
    calls = 0,
    applied = 0;
  const h = harness("document-ocr-review", {
    read: () => {
      calls++;
      return new Promise((done) => {
        resolve = done;
      });
    },
  });
  const p = props({ ...complete, status: "queued", segments: [] }, { onApplied: () => applied++ });
  h.render("DocumentOcrReview", p);
  assert.equal([...h.timers.values()][0].ms, 2000);
  const [id, timer] = [...h.timers][0];
  h.timers.delete(id);
  const inFlight = timer.fn();
  h.unmount();
  resolve(complete);
  await inFlight;
  assert.equal(calls, 1);
  assert.equal(h.timers.size, 0);
  assert.equal(applied, 0);
  assert.ok(!h.state.some((s) => s?.status === "completed"));
});
test("新识别请求立即阻止确认，识别失败保留外层原预检正文", async () => {
  const pending = [];
  const h = harness("document-ocr-review", {
    write: async () => {
      throw new Error("OCR未配置");
    },
  });
  const p = {
    ...props(),
    initial: { ...complete, status: "failed", segments: [] },
    onPendingChange: (v) => pending.push(v),
  };
  await button(h.render("DocumentOcrReview", p), "重试文字识别").props.onClick();
  const tree = h.render("DocumentOcrReview", p);
  assert.equal(pending[0], true);
  assert.match(text(tree), /OCR未配置/);
});
test("queued→running→completed停止轮询并以真实候选填充textarea", async () => {
  const statuses = [{ ...complete, status: "running", segments: [] }, complete];
  const h = harness("document-ocr-review", { read: async () => statuses.shift() });
  const p = props({ ...complete, status: "queued", segments: [] });
  let tree = h.render("DocumentOcrReview", p);
  assert.match(text(tree), /等待识别/);
  const tick = async (expected) => {
    const [id, timer] = [...h.timers][0];
    h.timers.delete(id);
    await timer.fn();
    tree = h.render("DocumentOcrReview", p);
    assert.match(text(tree), new RegExp(expected));
  };
  await tick("正在识别");
  await tick("第2页");
  assert.equal(h.timers.size, 0);
  assert.equal(nodes(tree).find((n) => n.type === "textarea").props.value, "原始候选错字");
  const { renderToStaticMarkup } = require("react-dom/server");
  assert.match(renderToStaticMarkup(tree), /textarea[^>]*>原始候选错字<\/textarea>/);
});
test("采用网络失败保留人工文字与核对状态，编辑后重新核对", async () => {
  const h = harness("document-ocr-review", {
    write: async () => {
      throw new Error("保存失败");
    },
  });
  const p = props();
  let tree = h.render("DocumentOcrReview", p);
  nodes(tree)
    .find((n) => n.type === "textarea")
    .props.onChange({ target: { value: "人工修订保留" } });
  tree = h.render("DocumentOcrReview", p);
  nodes(tree)
    .find((n) => n.type === "input" && n.props.type === "checkbox")
    .props.onChange({ target: { checked: true } });
  tree = h.render("DocumentOcrReview", p);
  await button(tree, "采用核对结果").props.onClick();
  tree = h.render("DocumentOcrReview", p);
  assert.match(text(tree), /保存失败/);
  assert.equal(nodes(tree).find((n) => n.type === "textarea").props.value, "人工修订保留");
  nodes(tree)
    .find((n) => n.type === "textarea")
    .props.onChange({ target: { value: "再次修订" } });
  tree = h.render("DocumentOcrReview", p);
  assert.equal(button(tree, "采用核对结果").props.disabled, true);
});
test("关闭尚未GET的轮询清timer，已关闭的POST启动响应不修改状态", async () => {
  const waiting = harness("document-ocr-review");
  waiting.render("DocumentOcrReview", props({ ...complete, status: "running" }));
  assert.equal(waiting.timers.size, 1);
  waiting.unmount();
  assert.equal(waiting.timers.size, 0);
  let resolve;
  const h = harness("document-ocr-review", {
    write: () =>
      new Promise((done) => {
        resolve = done;
      }),
  });
  const p = { ...props(), initial: { ...complete, status: "failed", segments: [] } };
  const pending = button(h.render("DocumentOcrReview", p), "重试文字识别").props.onClick();
  h.unmount();
  resolve(complete);
  await pending;
  assert.equal(h.state[0].status, "failed");
});
test("采用后的预检才允许导入；confirmed原件及文本导入不显示OCR", () => {
  for (const kind of ["candidate", "reviewed", "confirmed", "text"]) {
    const h = harness("document-import-form");
    h.state[0] = { name: kind === "text" ? "source.txt" : "scan.pdf" };
    h.state[1] = {
      ...preview,
      status: kind === "confirmed" ? "confirmed" : "preview",
      extraction: {
        format: kind === "text" ? "txt" : "pdf",
        ...(kind === "candidate"
          ? { ocr: complete }
          : kind === "reviewed"
            ? { ocr: { ...complete, reviewed: true, requires_review: false } }
            : {}),
      },
    };
    const tree = h.render("DocumentImportForm", { base: "/q/", resource: "knowledge", onClose() {}, onSaved() {} });
    assert.equal(!!tree.props.onSubmit, kind !== "candidate");
    assert.equal(
      nodes(tree).some((n) => n.type === stub("DocumentOcrReview")),
      kind === "candidate" || kind === "reviewed"
    );
  }
});
test("文件窗口取消不清空已有预检与选择，采用保存期间禁止改文字", async () => {
  const parent = harness("document-import-form");
  parent.state[0] = { name: "scan.pdf" };
  parent.state[1] = preview;
  const p = { base: "/q/", resource: "knowledge", onClose() {}, onSaved() {} };
  const tree = parent.render("DocumentImportForm", p);
  nodes(tree)
    .find((n) => n.type === "input" && n.props.type === "file")
    .props.onChange({ target: { files: [] } });
  assert.equal(parent.state[1], preview);
  assert.equal(parent.state[0].name, "scan.pdf");
  let resolve;
  const h = harness("document-ocr-review", {
    write: () =>
      new Promise((done) => {
        resolve = done;
      }),
  });
  let child = h.render("DocumentOcrReview", props());
  nodes(child)
    .find((n) => n.type === "input" && n.props.type === "checkbox")
    .props.onChange({ target: { checked: true } });
  child = h.render("DocumentOcrReview", props());
  const saving = button(child, "采用核对结果").props.onClick();
  child = h.render("DocumentOcrReview", props());
  assert.equal(nodes(child).find((n) => n.type === "textarea").props.disabled, true);
  resolve(preview);
  await saving;
});
test("原件PNG预览复用安全preview_url，下载仍独立；PDF无预览按钮", async () => {
  const calls = [];
  const h = harness("document-source-files", {
    blob: async (url) => {
      calls.push(["preview", url]);
      return new Blob(["test"]);
    },
    download: async (...args) => calls.push(["download", ...args]),
  });
  const original = {
    id: "f1",
    kind: "original",
    name: "scan.png",
    download_url: "/safe/file/",
    preview_url: "/safe/file/?preview=1",
    size: 10,
    sha256: "x",
  };
  let tree = h.render("DocumentSourceFiles", { files: [original] });
  await button(tree, "查看原图").props.onClick();
  tree = h.render("DocumentSourceFiles", { files: [original] });
  assert.equal(nodes(tree).find((n) => n.type === "img").props.alt, "scan.png");
  await button(tree, "下载完整原件").props.onClick();
  assert.deepEqual(calls, [
    ["preview", "/safe/file/?preview=1"],
    ["download", "/safe/file/", "scan.png"],
  ]);
  h.unmount();
  const pdf = harness("document-source-files");
  assert.equal(
    button(
      pdf.render("DocumentSourceFiles", { files: [{ ...original, name: "source.pdf", preview_url: null }] }),
      "查看原图"
    ),
    undefined
  );
});
test("导入表单仅知识接受PNG并提供OCR，候选未经采用不得确认，原预检保留", () => {
  for (const resource of ["knowledge", "requirements", "versions"]) {
    const h = harness("document-import-form");
    h.state[0] = { name: "scan.png" };
    h.state[1] = { ...preview, extraction: { format: "png", ocr: complete } };
    const tree = h.render("DocumentImportForm", { base: "/q/", resource, onClose() {}, onSaved() {} });
    const input = nodes(tree).find((n) => n.type === "input" && n.props.type === "file");
    assert.equal(input.props.accept.includes(".png"), resource === "knowledge");
    assert.equal(
      nodes(tree).some((n) => n.type === stub("DocumentOcrReview")),
      resource === "knowledge"
    );
    if (resource === "knowledge") assert.equal(tree.props.onSubmit, undefined);
    assert.match(text(tree), /原预检正文/);
  }
});

test("自动排队和正常候选不再要求用户选择识别，失败才显示重试", () => {
  for (const status of ["queued", "running", "completed"]) {
    const h = harness("document-ocr-review");
    const tree = h.render("DocumentOcrReview", props({ ...complete, status }));
    assert.equal(button(tree, "重试文字识别"), undefined);
  }
});
