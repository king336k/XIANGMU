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
      useRef: () => ({ current: true }),
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
  assert.equal(nodes(history).filter((node) => node.type === "details").length, 3);
  assert.match(JSON.stringify(history), /第5轮结果/);
  assert.doesNotMatch(JSON.stringify(history), /第8轮结果/);
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
    ["upload_start", "upload_chunk", "upload_finish"]
  );
  for (const reset of [
    [8, undefined],
    [4, undefined],
    [2, ""],
    [3, undefined],
    [10, ""],
    [9, undefined],
    [11, false],
  ]) {
    assert.ok(
      changes.some(([index, value]) => index === reset[0] && value === reset[1]),
      `successful upload resets state ${reset[0]}`
    );
  }
  assert.ok(changes.some(([index, value]) => index === 6 && value === "已上传并校验：incoming/retry-name.zip"));
  assert.match(JSON.stringify(tree), /机器人：/);
});

test("文件位置用采集电脑称谓并保留实际用户名", () => {
  const { exports } = load("./file-panel.tsx", []);
  const tree = exports.FilePanel({ device });
  const caption = nodes(tree).find((node) => node.type === "option" && node.props.value === "operator");
  assert.equal(caption.props.children.join(""), "采集电脑：caiji1@10.0.0.195");
  const robot = nodes(tree).find((node) => node.type === "option" && node.props.value === "robot");
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
  assert.match(JSON.stringify(history), /验证正常/);
  assert.match(JSON.stringify(history), /text-success-primary/);
  assert.doesNotMatch(JSON.stringify(history), /需跟进/);
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

test("file manager keeps upload and download in the left toolbar and waits for explicit confirmation", () => {
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
  const toolbar = nodes(tree).find((node) => node.props?.["aria-label"] === "文件操作");
  const buttons = nodes(toolbar).filter((node) => node.type === "button");
  assert.equal(buttons.length, 3);
  assert.match(JSON.stringify(buttons[0]), /上传/);
  assert.match(JSON.stringify(buttons[1]), /下载/);
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

test("verified download closes and clears both sides only after invoking browser save", async () => {
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
    for (const [index, expected] of [
      [8, undefined],
      [4, undefined],
      [2, ""],
      [3, undefined],
      [10, ""],
      [9, undefined],
      [11, false],
    ])
      assert.ok(loaded.changes.some(([key, value]) => key === index && value === expected));
    assert.ok(loaded.changes.some(([index, value]) => index === 6 && value === "已校验并下载 trace.log"));
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
  const toolbar = nodes(exports.FilePanel({ device })).find((node) => node.props?.["aria-label"] === "文件操作");
  nodes(toolbar)
    .filter((node) => node.type === "button")[1]
    .props.onClick();
  for (const [index, expected] of [
    [8, undefined],
    [4, undefined],
    [2, ""],
    [3, undefined],
    [10, ""],
    [9, undefined],
    [11, true],
    [12, "download"],
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
