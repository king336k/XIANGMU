import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../../../package.json", import.meta.url));
const ts = require("typescript");
const React = require("react");
const device = {
  id: "computer",
  username: "caiji1",
  hostname: "operator195",
  ip_address: "10.0.0.195",
  workspace_slug: "workspace",
  project_id: "project",
  online: true,
  can_connect: true,
  capabilities: { robot: { username: "robot-user", host: "10.0.0.177" } },
};
const api = {};
new Function(
  "exports",
  ts.transpileModule(readFileSync(new URL("./types.ts", import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS },
  }).outputText
)(api);
function nodes(tree) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
function load(file, states, extra = {}) {
  let cursor = 0;
  const changes = [];
  const exports = {};
  const mocks = {
    react: {
      ...React,
      useState: (initial) => {
        const index = cursor++;
        return [index < states.length ? states[index] : initial, (value) => changes.push([index, value])];
      },
      useEffect() {},
      useRef: (initial) => ({ current: initial }),
    },
    "react/jsx-runtime": require("react/jsx-runtime"),
    "lucide-react": {
      Download: () => null,
      Folder: () => null,
      FileText: () => null,
      ArrowUp: () => null,
      RefreshCw: () => null,
      ArrowLeft: () => null,
      ArrowRight: () => null,
      FolderOpen: () => null,
      Upload: () => null,
    },
    "./types": api,
    "./feedback-picker": { FeedbackPicker: () => null },
    "./remote-feedback-history": { RemoteFeedbackHistory: () => null },
    "./transfer-modal": { TransferModal: () => null },
    "@/components/quality/shared": { fieldClass: "field" },
    "@/components/quality/api": { qualityApi: {}, errorMessage: (error) => error.message },
    ...extra,
  };
  new Function(
    "require",
    "exports",
    "setTimeout",
    ts.transpileModule(readFileSync(new URL(file, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((name) => mocks[name] ?? require(name), exports, extra.setTimeout || setTimeout);
  return { exports, changes };
}

async function cancelledUploadAtResponse(file, unmountAt) {
  let cleanup;
  let hookIndex = 0;
  let refIndex = 0;
  let finishResponse;
  const writes = [];
  const changes = [];
  const states = [
    "operator",
    "",
    "incoming",
    { root: "/home/caiji1", entries: [], total: 0 },
    undefined,
    false,
    "",
    "",
    file,
    undefined,
    file.name,
    true,
    "upload",
  ];
  const { exports } = load("./file-panel.tsx", [], {
    react: {
      ...React,
      useState(initial) {
        const index = hookIndex++;
        return [index < states.length ? states[index] : initial, (value) => changes.push([index, value])];
      },
      useRef: () => ({ current: refIndex++ === 0 ? null : 0 }),
      useEffect: (effect) => {
        cleanup = effect();
      },
    },
    "@noble/hashes/sha256": { sha256: () => new Uint8Array(32).fill(1) },
    "@/components/quality/api": {
      errorMessage: (error) => error.message,
      qualityApi: {
        async write(url, body) {
          writes.push(body.action);
          return { id: body.action };
        },
        async read(url) {
          const action = url.split("/").at(-2);
          if (action === unmountAt)
            return new Promise((resolve) => {
              finishResponse = resolve;
            });
          return {
            status: "done",
            error: "",
            result: action === "upload_start" ? { ticket: "ticket" } : { next_offset: file.size },
          };
        },
      },
    },
  });
  nodes(exports.FilePanel({ device }))
    .find((node) => node.props?.onStart)
    .props.onStart();
  await new Promise((resolve) => setImmediate(resolve));
  const before = writes.slice();
  const uiUpdates = changes.length;
  cleanup();
  finishResponse({
    status: "done",
    error: "",
    result:
      unmountAt === "upload_start"
        ? { ticket: "ticket" }
        : { uploaded: true, sha256: "01".repeat(32), path: `incoming/${file.name}` },
  });
  await new Promise((resolve) => setImmediate(resolve));
  return { writes, before, changes, uiUpdates };
}

test("unmount during upload-start ignores the late response without chunks finish abort or UI updates", async () => {
  await Promise.all(
    [new File(["data"], "chunk.zip"), new File([], "empty.zip")].map(async (file) => {
      const result = await cancelledUploadAtResponse(file, "upload_start");
      assert.deepEqual(result.before, ["upload_start"]);
      assert.deepEqual(result.writes, result.before);
      assert.equal(result.changes.length, result.uiUpdates);
    })
  );
});

test("unmount while hashing prevents even the initial upload-start mutation", async () => {
  let cleanup;
  let resolveHash;
  let refIndex = 0;
  const writes = [];
  const file = new File(["data"], "pending.zip");
  file.arrayBuffer = () =>
    new Promise((resolve) => {
      resolveHash = resolve;
    });
  const baseReact = {
    ...React,
    useEffect: (effect) => {
      cleanup = effect();
    },
    useRef: () => ({ current: refIndex++ === 0 ? null : 0 }),
  };
  let stateIndex = 0;
  const values = [
    "operator",
    "",
    "incoming",
    { root: "/home/caiji1", entries: [], total: 0 },
    undefined,
    false,
    "",
    "",
    file,
    undefined,
    file.name,
    true,
    "upload",
  ];
  const { exports } = load("./file-panel.tsx", [], {
    react: {
      ...baseReact,
      useState: (initial) => [stateIndex < values.length ? values[stateIndex++] : initial, () => {}],
    },
    "@noble/hashes/sha256": { sha256: () => new Uint8Array(32).fill(1) },
    "@/components/quality/api": {
      qualityApi: {
        async write(url, body) {
          writes.push(body.action);
          return { id: "job" };
        },
      },
      errorMessage: String,
    },
  });
  nodes(exports.FilePanel({ device }))
    .find((node) => node.props?.onStart)
    .props.onStart();
  await new Promise((resolve) => setImmediate(resolve));
  cleanup();
  resolveHash(new ArrayBuffer(4));
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(writes, []);
});

test("unmount during upload-finish ignores late acknowledgement and does not refresh or mark success", async () => {
  const result = await cancelledUploadAtResponse(new File([], "empty.zip"), "upload_finish");
  assert.deepEqual(result.before, ["upload_start", "upload_finish"]);
  assert.deepEqual(result.writes, result.before);
  assert.equal(result.changes.length, result.uiUpdates);
});

test("Agent selected feedback history shows three rounds per page and preserves old results", () => {
  const replies = Array.from({ length: 8 }, (_, index) => ({
    id: `reply-${index}`,
    visibility: "public",
    created_at: `2026-11-${String(index + 1).padStart(2, "0")}T00:00:00Z`,
    content: `Agent 远程处理：${index % 2 ? "已修复" : "未自动修复"}\n结论：第${index + 1}轮结果`,
  }));
  const { exports, changes } = load(
    "./agent-panel.tsx",
    [{ id: "fb", code: "D-51", title: "反馈" }, "problem", false, null, "", 2],
    {
      swr: {
        default: (url) => ({
          data: url?.includes("collaboration")
            ? replies
            : { count: 101, results: [{ id: "fb", code: "D-51", title: "反馈", run_count: 8 }] },
          mutate() {},
        }),
      },
    }
  );
  const tree = exports.AgentPanel({ device });
  const history = nodes(tree).find((node) => node.props?.["aria-label"] === "所选反馈处理历史");
  const renderedHistory = nodes(history).find((node) => Array.isArray(node.props?.replies));
  assert.equal(renderedHistory.props.page, 2);
  assert.deepEqual(
    renderedHistory.props.replies.slice(3, 6).map((reply) => reply.id),
    ["reply-4", "reply-3", "reply-2"]
  );
  assert.equal(renderedHistory.props.replies.length, 8);
  nodes(history)
    .find((node) => node.type === "button" && node.props.children === "上一页")
    .props.onClick();
  assert.deepEqual(changes.at(-1), [5, 1]);
});

test("upload sends edited filename and exact selected defect, then checks remote digest", async () => {
  const file = new File(["patch-data"], "original.zip");
  const listing = { root: "/home/robot-user", path: "incoming", entries: [], total: 0, offset: 0 };
  const writes = [];
  const digest = "01".repeat(32);
  const jobs = new Map();
  const { exports, changes } = load(
    "./file-panel.tsx",
    [
      "robot",
      "robot-user",
      "incoming",
      listing,
      undefined,
      false,
      "",
      "",
      file,
      { id: "fb-51", code: "D-51", title: "反馈" },
      "retry-name.zip",
      true,
      "upload",
    ],
    {
      swr: {
        default: () => {
          return { data: { count: 101, results: [{ id: "fb-51", code: "D-51", title: "反馈" }] } };
        },
      },
      "@noble/hashes/sha256": { sha256: () => new Uint8Array(32).fill(1) },
      "@/components/quality/api": {
        errorMessage: (error) => error.message,
        qualityApi: {
          async write(url, body) {
            writes.push(body);
            const id = String(writes.length);
            jobs.set(id, body);
            return { id };
          },
          async read(url) {
            const body = jobs.get(url.split("/").at(-2));
            return {
              status: "done",
              error: "",
              result:
                body.action === "upload_start"
                  ? { ticket: "ticket" }
                  : body.action === "upload_chunk"
                    ? { next_offset: file.size }
                    : body.action === "upload_finish"
                      ? { uploaded: true, sha256: digest, path: "incoming/retry-name.zip" }
                      : listing,
            };
          },
        },
      },
    }
  );
  const tree = exports.FilePanel({ device });
  const modal = nodes(tree).find((node) => node.props?.onStart);
  modal.props.onStart();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(writes[0].action, "upload_start");
  assert.equal(writes[0].defect_id, "fb-51");
  assert.equal(writes[0].filename, "retry-name.zip");
  assert.equal(writes[0].target, "robot");
  assert.equal(writes[0].path, "incoming");
  assert.deepEqual(
    writes.map((body) => body.action),
    ["upload_start", "upload_chunk", "upload_finish", "list"]
  );
  assert.equal(
    changes.some(([index]) => [2, 8, 9, 10, 11].includes(index)),
    false,
    "success keeps modal and local source for another explicit transfer"
  );
  assert.ok(changes.some(([index, value]) => index === 4 && value === undefined));
  assert.ok(changes.some(([index, value]) => index === 3 && value === listing));
  assert.ok(
    changes.some(
      ([index, value]) =>
        index === 6 && value === "已上传并校验：robot-user@10.0.0.177:/home/robot-user/incoming/retry-name.zip"
    )
  );
  const completed = changes.find(([index]) => index === 13)[1];
  assert.equal(completed.target, "robot");
  assert.equal(completed.path, "incoming");
  assert.equal(completed.fullPath, "/home/robot-user/incoming/retry-name.zip");
  assert.ok(Number.isFinite(Date.parse(completed.completedAt)));
  assert.match(JSON.stringify(tree), /机器人：/);
});

test("文件位置用采集电脑称谓并保留实际用户名", () => {
  const { exports } = load("./file-panel.tsx", [
    "operator",
    "robot-user",
    "",
    undefined,
    undefined,
    false,
    "",
    "",
    undefined,
    undefined,
    "",
    true,
    "upload",
  ]);
  const tree = exports.FilePanel({ device });
  const target = nodes(tree).find((node) => node.props?.onStart).props.targetControl;
  const caption = nodes(target).find((node) => node.type === "option" && node.props.value === "operator");
  assert.equal(caption.props.children.join(""), "采集电脑：caiji1@10.0.0.195");
  const robot = nodes(target).find((node) => node.type === "option" && node.props.value === "robot");
  assert.equal(robot.props.children.join(""), "机器人：robot-user@10.0.0.177");
  assert.doesNotMatch(JSON.stringify(tree), /操作电脑/);
});

test("upload rejects a target filename containing a path before any network mutation", async () => {
  let count = 0;
  const { exports } = load(
    "./file-panel.tsx",
    [
      "operator",
      "",
      "",
      { root: "/home/caiji1", entries: [], total: 0 },
      undefined,
      false,
      "",
      "",
      new File(["data"], "patch.zip"),
      undefined,
      "../escape.zip",
      true,
      "upload",
    ],
    {
      swr: { default: () => ({ data: { count: 0, results: [] } }) },
      "@/components/quality/api": {
        errorMessage: String,
        qualityApi: {
          async write() {
            count++;
          },
        },
      },
    }
  );
  nodes(exports.FilePanel({ device }))
    .find((node) => node.props?.onStart)
    .props.onStart();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(count, 0);
});

test("verify-only result is green only with explicit verification evidence and verified outcome", () => {
  for (const [result, normal] of [
    [{ repaired: false, verification_passed: true, outcome: "verified" }, true],
    [{ repaired: false, outcome: "verified" }, false],
    [{ repaired: false, verification_passed: false, outcome: "unresolved" }, false],
  ]) {
    const { exports } = load(
      "./agent-panel.tsx",
      [{ id: "fb", code: "D-51", title: "反馈" }, "problem", false, { id: "run", status: "completed", result }, "", 1],
      {
        swr: {
          default: (url) => ({
            data: url?.includes("collaboration")
              ? []
              : { count: 1, results: [{ id: "fb", code: "D-51", title: "反馈" }] },
            mutate() {},
          }),
        },
      }
    );
    const tree = exports.AgentPanel({ device });
    const status = nodes(tree).find((node) => node.type === "p" && node.props.role === "status");
    assert.equal(JSON.stringify(status).includes("验证正常"), normal);
    assert.equal(JSON.stringify(status).includes("text-success-primary"), normal);
  }
});

test("explicit verification report appears in selected feedback history as green verification", () => {
  const { exports } = load(
    "./agent-panel.tsx",
    [{ id: "fb", code: "D-51", title: "反馈" }, "problem", false, null, "", 1],
    {
      swr: {
        default: (url) => ({
          data: url?.includes("collaboration")
            ? [
                {
                  id: "verified",
                  visibility: "public",
                  created_at: "2026-11-18T00:00:00Z",
                  content: "Agent 远程处理：验证通过\n结论：固定检查通过",
                },
              ]
            : { count: 1, results: [{ id: "fb", code: "D-51", title: "反馈", latest_status: "verified" }] },
          mutate() {},
        }),
      },
    }
  );
  const history = nodes(exports.AgentPanel({ device })).find(
    (node) => node.props?.["aria-label"] === "所选反馈处理历史"
  );
  const renderedHistory = nodes(history).find((node) => Array.isArray(node.props?.replies));
  assert.equal(renderedHistory.props.replies[0].content, "Agent 远程处理：验证通过\n结论：固定检查通过");
});

test("feedback dialog searches only the current computer and commits a candidate only on confirm", async () => {
  const candidate = { id: "fb-next", code: "D-474", title: "采集503", latest_status: "unresolved" };
  const selected = { id: "fb-old", code: "D-1", title: "之前选择" };
  const confirmations = [];
  let closed = 0;
  const extra = {
    swr: {
      default: (url) => {
        assert.match(url, /device_id=computer/);
        assert.match(url, /q=503/);
        assert.match(url, /page=2/);
        return { data: { count: 31, results: [candidate] } };
      },
    },
  };
  const first = load("./feedback-picker.tsx", ["503", "503", 2, "all", selected], extra);
  const props = {
    device,
    value: selected,
    onClose: () => {
      closed++;
    },
    onConfirm: (value) => confirmations.push(value),
  };
  const tree = first.exports.FeedbackPickerDialog(props);
  nodes(tree)
    .find((node) => node.type === "input" && node.props.type === "radio")
    .props.onChange();
  assert.deepEqual(first.changes.at(-1), [4, candidate]);
  assert.equal(confirmations.length, 0);
  tree.props.onClose();
  assert.equal(closed, 1);
  assert.equal(confirmations.length, 0);
  const next = load("./feedback-picker.tsx", ["503", "503", 2, "all", candidate], extra).exports.FeedbackPickerDialog(
    props
  );
  await next.props.onSubmit();
  assert.deepEqual(confirmations, [candidate]);
});

test("main file panel has a single transfer entry and keeps browsing only inside the modal", () => {
  const { exports, changes } = load("./file-panel.tsx", [
    "operator",
    "",
    "",
    undefined,
    undefined,
    false,
    "",
    "",
    undefined,
    undefined,
    "",
    false,
  ]);
  const tree = exports.FilePanel({ device });
  const buttons = nodes(tree).filter((node) => node.type === "button");
  assert.equal(buttons.length, 1);
  assert.equal(buttons[0].props["aria-label"], "打开文件传输");
  assert.equal(
    nodes(tree).some((node) => ["select", "table"].includes(node.type)),
    false
  );
  assert.equal(
    nodes(tree).some((node) => node.props?.["aria-label"] === "上一级目录"),
    false
  );
  const input = nodes(tree).find((node) => node.type === "input" && node.props.type === "file");
  assert.equal(input.props.className, "hidden");
  const file = new File(["data"], "archive.zip");
  input.props.onChange({ target: { files: [file] }, currentTarget: { value: "file" } });
  assert.deepEqual(changes, [
    [8, file],
    [10, "archive.zip"],
  ]);
  assert.equal(
    nodes(tree).some((node) => node.props?.title === "确认上传"),
    false
  );
});

test("feedback picker defaults to five rows and switching to ten resets only page", () => {
  const candidate = { id: "fb", code: "D-474", title: "反馈" };
  const { exports, changes } = load("./feedback-picker.tsx", ["503", "503", 3, "all", candidate], {
    swr: {
      default: (url) => {
        assert.match(url, /per_page=5/);
        assert.match(url, /q=503/);
        assert.match(url, /state=all/);
        return { data: { count: 21, results: [candidate] } };
      },
    },
  });
  const tree = exports.FeedbackPickerDialog({ device, value: candidate, onClose() {}, onConfirm() {} });
  nodes(tree)
    .find((node) => node.props?.["aria-label"] === "每页反馈数量")
    .props.onChange({ target: { value: "10" } });
  assert.deepEqual(changes, [
    [5, 10],
    [2, 1],
  ]);
});

test("transfer dialog is two panes, shows browser destination honestly and starts only on explicit action", () => {
  let transfers = 0;
  const directions = [];
  const { exports } = load("./transfer-modal.tsx", []);
  const tree = exports.TransferModal({
    direction: "download",
    onDirection: (value) => directions.push(value),
    targetControl: "采集电脑：caiji1@10.0.0.195",
    remoteBrowser: "远端列表",
    localFile: undefined,
    remoteName: "logs.tar.gz",
    remotePath: "caiji1@10.0.0.195:/home/caiji1/logs",
    uploadName: "",
    onUploadName() {},
    onPickLocal() {},
    advanced: null,
    busy: false,
    enabled: true,
    message: "",
    error: "",
    onStart: () => {
      transfers++;
    },
    onClose() {},
  });
  assert.equal(nodes(tree).filter((node) => node.type === "section").length, 2);
  assert.match(JSON.stringify(tree), /浏览器下载目录/);
  assert.doesNotMatch(JSON.stringify(tree), /C:\\|\/home\/local/);
  nodes(tree)
    .find((node) => node.props?.["aria-label"] === "上传到远端")
    .props.onClick();
  assert.deepEqual(directions, ["upload"]);
  assert.equal(transfers, 0);
  nodes(tree)
    .find((node) => node.type === "button" && node.props.children === "开始传输")
    .props.onClick();
  assert.equal(transfers, 1);
});

test("changing transfer target resets remote directory and selection without launching a transfer", () => {
  let mutations = 0;
  const { exports, changes } = load(
    "./file-panel.tsx",
    [
      "operator",
      "robot-user",
      "logs",
      { root: "/home/caiji1", entries: [], total: 0 },
      { name: "old.log" },
      false,
      "",
      "",
      undefined,
      undefined,
      "",
      true,
      "download",
    ],
    {
      "@/components/quality/api": {
        qualityApi: {
          async write() {
            mutations++;
          },
        },
        errorMessage: String,
      },
    }
  );
  const tree = exports.FilePanel({ device });
  const modal = nodes(tree).find((node) => node.props?.onStart);
  modal.props.targetControl.props.onChange({ target: { value: "robot" } });
  assert.deepEqual(changes.slice(0, 4), [
    [0, "robot"],
    [3, undefined],
    [4, undefined],
    [2, ""],
  ]);
  assert.equal(mutations, 0);
  modal.props.onClose();
  assert.equal(mutations, 0);
  for (const [index, expected] of [
    [8, undefined],
    [4, undefined],
    [2, ""],
    [3, undefined],
    [10, ""],
    [9, undefined],
    [11, false],
  ])
    assert.ok(
      changes.some(([key, value]) => key === index && value === expected),
      `close clears selection ${index}`
    );
});

test("failed upload keeps modal and selections for retry without claiming success", async () => {
  const file = new File(["data"], "retry.zip");
  const { exports, changes } = load(
    "./file-panel.tsx",
    [
      "operator",
      "",
      "incoming",
      { root: "/home/caiji1", entries: [], total: 0 },
      { name: "old" },
      false,
      "",
      "",
      file,
      { id: "fb", code: "D-474", title: "反馈" },
      "retry.zip",
      true,
      "upload",
    ],
    {
      "@noble/hashes/sha256": { sha256: () => new Uint8Array(32).fill(1) },
      "@/components/quality/api": {
        qualityApi: {
          async write() {
            throw new Error("同名文件已存在");
          },
        },
        errorMessage: (error) => error.message,
      },
    }
  );
  nodes(exports.FilePanel({ device }))
    .find((node) => node.props?.onStart)
    .props.onStart();
  await new Promise((resolve) => setImmediate(resolve));
  assert.ok(changes.some(([index, value]) => index === 7 && value === "同名文件已存在"));
  assert.equal(
    changes.some(([index]) => [2, 3, 4, 8, 9, 10, 11].includes(index)),
    false
  );
});

test("directory refresh failure after verified upload preserves success and does not abort the upload", async () => {
  const actions = [];
  const { exports, changes } = load(
    "./file-panel.tsx",
    [
      "operator",
      "",
      "incoming",
      { root: "/home/caiji1", entries: [], total: 0 },
      undefined,
      false,
      "",
      "",
      new File([], "empty.zip"),
      undefined,
      "empty.zip",
      true,
      "upload",
    ],
    {
      "@noble/hashes/sha256": { sha256: () => new Uint8Array(32).fill(1) },
      "@/components/quality/api": {
        qualityApi: {
          async write(url, body) {
            actions.push(body.action);
            return { id: body.action };
          },
          async read(url) {
            const action = url.split("/").at(-2);
            if (action === "list") throw new Error("network");
            return {
              status: "done",
              error: "",
              result:
                action === "upload_start"
                  ? { ticket: "ticket" }
                  : { uploaded: true, sha256: "01".repeat(32), path: "incoming/empty.zip" },
            };
          },
        },
        errorMessage: (error) => error.message,
      },
    }
  );
  nodes(exports.FilePanel({ device }))
    .find((node) => node.props?.onStart)
    .props.onStart();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(actions, ["upload_start", "upload_finish", "list"]);
  assert.ok(changes.some(([index, value]) => index === 6 && value.includes("已上传并校验")));
  assert.ok(changes.some(([index, value]) => index === 7 && value.includes("文件已上传，但目录刷新失败")));
  assert.equal(
    changes.some(([index]) => [8, 9, 10, 11].includes(index)),
    false
  );
});

test("verified download leaves dialog available after invoking browser save", async () => {
  const previousDocument = globalThis.document;
  let saved = false;
  const changesAtSave = [];
  const listing = { root: "/home/caiji1", entries: [], total: 0 };
  let currentChanges;
  globalThis.document = {
    createElement: () => ({
      click() {
        saved = true;
        changesAtSave.push(...currentChanges);
      },
    }),
  };
  try {
    const loaded = load(
      "./file-panel.tsx",
      [
        "operator",
        "",
        "logs",
        listing,
        { name: "trace.log" },
        false,
        "",
        "",
        undefined,
        undefined,
        "",
        true,
        "download",
      ],
      {
        setTimeout: () => 0,
        "@noble/hashes/sha256": { sha256: () => new Uint8Array(32).fill(1) },
        "@/components/quality/api": {
          qualityApi: {
            async write() {
              return { id: "download" };
            },
            async read() {
              return {
                status: "done",
                error: "",
                result: { ticket: "ticket", filename: "trace.log", size: 0, sha256: "01".repeat(32), skipped: 0 },
              };
            },
          },
          errorMessage: (error) => error.message,
        },
      }
    );
    currentChanges = loaded.changes;
    nodes(loaded.exports.FilePanel({ device }))
      .find((node) => node.props?.onStart)
      .props.onStart();
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(saved, true);
    assert.equal(
      changesAtSave.some(([index, value]) => index === 11 && value === false),
      false
    );
    assert.equal(
      loaded.changes.some(([index]) => [2, 3, 4, 8, 9, 10, 11].includes(index)),
      false,
      "download success does not close or clear current choices"
    );
    assert.ok(loaded.changes.some(([index, value]) => index === 6 && value === "已校验并发起下载 trace.log"));
  } finally {
    globalThis.document = previousDocument;
  }
});

test("a reopened transfer drops previous path file feedback and disables download until a new choice", () => {
  const { exports, changes } = load("./file-panel.tsx", [
    "operator",
    "",
    "previous",
    { root: "/home/caiji1", entries: [], total: 0 },
    { name: "previous.log" },
    false,
    "old result",
    "",
    new File(["data"], "old.zip"),
    { id: "old" },
    "old.zip",
    false,
    "upload",
  ]);
  nodes(exports.FilePanel({ device }))
    .find((node) => node.props?.["aria-label"] === "打开文件传输")
    .props.onClick();
  for (const [index, expected] of [
    [8, undefined],
    [4, undefined],
    [2, ""],
    [3, undefined],
    [10, ""],
    [9, undefined],
    [11, true],
    [12, "upload"],
  ])
    assert.ok(changes.some(([key, value]) => key === index && value === expected));
  const blank = load("./file-panel.tsx", [
    "operator",
    "",
    "",
    { root: "/home/caiji1", entries: [], total: 0 },
    undefined,
    false,
    "",
    "",
    undefined,
    undefined,
    "",
    true,
    "download",
  ]).exports.FilePanel({ device });
  assert.equal(nodes(blank).find((node) => node.props?.onStart).props.enabled, false);
});

test("view uploaded target restores only the verified destination and requests its actual target", async () => {
  const calls = [];
  const completed = {
    target: "robot",
    path: "incoming",
    fullPath: "/home/robot-user/incoming/patch.zip",
    deviceLabel: "robot-user@10.0.0.177",
    filename: "patch.zip",
    completedAt: "2026-11-18T10:00:00Z",
  };
  const { exports, changes } = load(
    "./file-panel.tsx",
    [
      "operator",
      "robot-user",
      "",
      undefined,
      undefined,
      false,
      "已上传并校验",
      "",
      undefined,
      undefined,
      "",
      false,
      "upload",
      completed,
    ],
    {
      "@/components/quality/api": {
        qualityApi: {
          async write(url, body) {
            calls.push(body);
            return { id: "list" };
          },
          async read() {
            return {
              status: "done",
              error: "",
              result: { root: "/home/robot-user", path: "incoming", entries: [], total: 0, offset: 0 },
            };
          },
        },
        errorMessage: String,
      },
    }
  );
  const tree = exports.FilePanel({ device });
  assert.match(JSON.stringify(tree), /最近上传/);
  assert.equal(
    nodes(tree).some((node) => ["select", "table"].includes(node.type)),
    false
  );
  nodes(tree)
    .find((node) => node.type === "button" && node.props.children === "查看目标目录")
    .props.onClick();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(calls, [{ device_id: "computer", target: "robot", action: "list", path: "incoming", offset: 0 }]);
  for (const [index, expected] of [
    [8, undefined],
    [4, undefined],
    [10, ""],
    [9, undefined],
    [0, "robot"],
    [12, "download"],
    [11, true],
  ])
    assert.ok(changes.some(([key, value]) => key === index && value === expected));
  assert.equal(
    changes.some(([index, value]) => index === 8 && value !== undefined),
    false
  );
});

test("selecting a file resets native input so the same package can target a second machine", () => {
  const file = new File(["transfer"], "same.zip");
  const { exports, changes } = load("./file-panel.tsx", [], {
    swr: { default: () => ({ data: { results: [], count: 0 } }) },
  });
  const input = nodes(exports.FilePanel({ device })).find(
    (node) => node.type === "input" && node.props.type === "file"
  );
  const currentTarget = { value: "same.zip" };
  input.props.onChange({ target: { files: [file] }, currentTarget });
  assert.equal(currentTarget.value, "");
  assert.ok(changes.some(([, value]) => value === file));
});
