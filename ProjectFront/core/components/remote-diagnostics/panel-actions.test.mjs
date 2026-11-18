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
  workspace_slug: "workspace",
  project_id: "project",
  online: true,
  can_connect: true,
  capabilities: { robot: { username: "robot-user" } },
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
    },
    "./types": api,
    "@/components/quality/shared": { fieldClass: "field" },
    "@/components/quality/api": { qualityApi: {}, errorMessage: (error) => error.message },
    ...extra,
  };
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(file, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((name) => mocks[name] ?? require(name), exports);
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
    ["", "", 1, "needs_attention", "fb", "problem", false, null, "", 2],
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
  assert.deepEqual(changes.at(-1), [9, 1]);
});

test("upload sends edited filename and exact selected defect, then checks remote digest", async () => {
  const file = new File(["patch-data"], "original.zip");
  const listing = { root: "/home/robot-user", path: "incoming", entries: [], total: 0, offset: 0 };
  const writes = [];
  const digest = "01".repeat(32);
  const jobs = new Map();
  const { exports } = load(
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
      "fb-51",
      "retry-name.zip",
      "D-51",
      "D-51",
      6,
    ],
    {
      swr: {
        default: (url) => {
          assert.match(url, /page=6/);
          assert.match(url, /q=D-51/);
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
  const button = nodes(tree).find((node) => node.type === "button" && node.props.children === "确认上传到当前目录");
  button.props.onClick();
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
  assert.match(JSON.stringify(tree), /机器人：/);
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
      "",
      "../escape.zip",
      "",
      "",
      1,
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
    .find((node) => node.type === "button" && node.props.children === "确认上传到当前目录")
    .props.onClick();
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
      ["", "", 1, "needs_attention", "fb", "problem", false, { id: "run", status: "completed", result }, "", 1],
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
  const { exports } = load("./agent-panel.tsx", ["", "", 1, "needs_attention", "fb", "problem", false, null, "", 1], {
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
  });
  const history = nodes(exports.AgentPanel({ device })).find(
    (node) => node.props?.["aria-label"] === "所选反馈处理历史"
  );
  assert.match(JSON.stringify(history), /验证正常/);
  assert.match(JSON.stringify(history), /text-success-primary/);
  assert.doesNotMatch(JSON.stringify(history), /需跟进/);
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
