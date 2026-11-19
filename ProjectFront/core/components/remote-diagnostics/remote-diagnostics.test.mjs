import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../../../package.json", import.meta.url));
const ts = require("typescript");
const React = require("react");

function load(file, mocks = {}) {
  const exports = {};
  const source = readFileSync(new URL(file, import.meta.url), "utf8");
  new Function(
    "require",
    "exports",
    ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((name) => mocks[name] ?? require(name), exports);
  return exports;
}
const { TerminalConnection, encodeTerminalInput, decodeTerminalOutput } = load("./terminal-connection.ts");
const types = load("./types.ts");
const flush = () => new Promise((resolve) => setImmediate(resolve));
const flushInputFrame = () => new Promise((resolve) => setTimeout(resolve, 40));

test("terminal preserves Unicode, escape sequences and Ctrl+C as bytes", () => {
  const input = "中文🙂\u001b[A\u0003";
  assert.deepEqual(decodeTerminalOutput(encodeTerminalInput(input)), new TextEncoder().encode(input));
});

test("robot terminal open binds only target and expected revision and reports actual session identity", async () => {
  const calls = [];
  let accepted;
  const session = {
    id: "robot-session",
    status: "open",
    target: "robot",
    identity: { username: "actual-robot", host: "10.0.0.177" },
    target_revision: "peer-revision",
  };
  const connection = new TerminalConnection(
    {
      read: () => new Promise(() => {}),
      async write(url, body) {
        calls.push(body);
        return session;
      },
    },
    "/remote/",
    () => {},
    () => {},
    (value) => {
      accepted = value;
    }
  );
  await connection.open("computer", 80, 24, "robot", "peer-revision");
  assert.deepEqual(calls[0], {
    action: "open",
    device_id: "computer",
    cols: 80,
    rows: 24,
    target: "robot",
    expected_target_revision: "peer-revision",
  });
  assert.equal(accepted.identity.username, "actual-robot");
  assert.equal(accepted.identity.host, "10.0.0.177");
  assert.equal("host" in calls[0] || "username" in calls[0] || "password" in calls[0], false);
  connection.dispose();
});

test("robot terminal rejects a mismatched response target and closes rather than sending robot input to collector", async () => {
  const calls = [];
  const statuses = [];
  const connection = new TerminalConnection(
    {
      read: () => {
        throw new Error("must not poll");
      },
      async write(url, body) {
        calls.push(body.action);
        return {
          id: "wrong",
          status: "open",
          target: "operator",
          identity: { username: "collector", host: "10.0.0.195" },
        };
      },
    },
    "/remote/",
    () => {},
    (value) => statuses.push(value)
  );
  await connection.open("computer", 80, 24, "robot", "peer-revision");
  connection.input("pwd\r");
  assert.deepEqual(statuses, ["connecting", "error"]);
  assert.deepEqual(calls, ["open", "close"]);
});

test("robot terminal without revision never sends an open request", async () => {
  const calls = [];
  const connection = new TerminalConnection(
    {
      read: () => new Promise(() => {}),
      async write(url, body) {
        calls.push(body);
        return {};
      },
    },
    "/remote/",
    () => {},
    () => {}
  );
  await connection.open("computer", 80, 24, "robot");
  assert.deepEqual(calls, []);
});

test("terminal serializes rapid input, preserves Ctrl+C and resizes the owned session", async () => {
  const calls = [];
  let release;
  const api = {
    read: () => new Promise(() => {}),
    async write(url, payload) {
      calls.push({ url, payload });
      if (payload.action === "open") return { id: "owned", status: "open" };
      if (payload.action === "input" && calls.length === 2)
        await new Promise((resolve) => {
          release = resolve;
        });
      return {};
    },
  };
  const connection = new TerminalConnection(
    api,
    "/remote/",
    () => {},
    () => {}
  );
  await connection.open("computer", 80, 24);
  connection.input("echo 中文\r");
  await flushInputFrame();
  connection.input("\u0003");
  connection.resize(120, 40);
  assert.equal(calls.length, 2);
  release();
  await flush();
  assert.deepEqual(
    calls.map((call) => call.payload.action),
    ["open", "input", "input", "resize"]
  );
  assert.equal(new TextDecoder().decode(decodeTerminalOutput(calls[2].payload.data)), "\u0003");
  assert.equal(calls[3].payload.cols, 120);
  assert.equal(calls[3].url, "/remote/sessions/owned/");
  connection.dispose();
  await flush();
  assert.equal(calls.at(-1).payload.action, "close");
});

test("closing while a terminal opens closes that late session without polling it", async () => {
  let resolveOpen;
  const calls = [];
  const connection = new TerminalConnection(
    {
      read() {
        throw new Error("must not poll disposed session");
      },
      write(url, payload) {
        calls.push({ url, payload });
        return payload.action === "open"
          ? new Promise((resolve) => {
              resolveOpen = resolve;
            })
          : Promise.resolve({});
      },
    },
    "/remote/",
    () => {},
    () => {}
  );
  const opening = connection.open("computer", 80, 24);
  connection.dispose();
  resolveOpen({ id: "late", status: "open" });
  await opening;
  assert.equal(calls.at(-1).url, "/remote/sessions/late/");
  assert.equal(calls.at(-1).payload.action, "close");
});

test("rapid individual keys coalesce into one ordered request and in-flight keys into the next", async () => {
  const inputs = [];
  let release;
  const connection = new TerminalConnection(
    {
      read: () => new Promise(() => {}),
      async write(url, body) {
        if (body.action === "open") return { id: "frame", status: "open" };
        if (body.action === "input") {
          inputs.push(new TextDecoder().decode(decodeTerminalOutput(body.data)));
          if (inputs.length === 1)
            await new Promise((resolve) => {
              release = resolve;
            });
        }
        return {};
      },
    },
    "/remote/",
    () => {},
    () => {}
  );
  await connection.open("computer", 80, 24);
  for (const key of "echo 你好") connection.input(key);
  assert.equal(inputs.length, 0);
  await flushInputFrame();
  assert.deepEqual(inputs, ["echo 你好"]);
  for (const key of " && pwd\r") connection.input(key);
  release();
  await flush();
  assert.deepEqual(inputs, ["echo 你好", " && pwd\r"]);
  connection.dispose();
});

test("large terminal paste stays inside the connector input limit without changing bytes", async () => {
  const chunks = [];
  const connection = new TerminalConnection(
    {
      read: () => new Promise(() => {}),
      async write(url, body) {
        if (body.action === "input") chunks.push(decodeTerminalOutput(body.data));
        return { id: "paste", status: "open" };
      },
    },
    "/remote/",
    () => {},
    () => {}
  );
  await connection.open("computer", 80, 24);
  const paste = "中文🙂".repeat(1000);
  connection.input(paste);
  await flushInputFrame();
  assert.equal(
    chunks.every((chunk) => chunk.length <= 4096),
    true
  );
  assert.deepEqual(Uint8Array.from(chunks.flatMap((chunk) => Array.from(chunk))), new TextEncoder().encode(paste));
  connection.dispose();
});

test("poll writes raw UTF8 chunks without decoding each chunk and ignores duplicate events", async () => {
  const bytes = new TextEncoder().encode("中");
  const output = [];
  const statuses = [];
  const connection = new TerminalConnection(
    {
      async write() {
        return { id: "pty", status: "open" };
      },
      async read(url) {
        assert.equal(url, "/remote/sessions/pty/?after=0");
        return {
          status: "closed",
          cursor: 2,
          events: [
            { seq: 1, data: btoa(String.fromCharCode(bytes[0])) },
            { seq: 1, data: btoa(String.fromCharCode(bytes[0])) },
            { seq: 2, data: btoa(String.fromCharCode(...bytes.slice(1))) },
          ],
        };
      },
    },
    "/remote/",
    (data) => output.push(...data),
    (status) => statuses.push(status)
  );
  await connection.open("computer", 80, 24);
  await flush();
  assert.deepEqual(Uint8Array.from(output), bytes);
  assert.deepEqual(statuses, ["connecting", "open", "closed"]);
});

test("a transport error reports disconnection and closes the PTY", async () => {
  const actions = [];
  const statuses = [];
  const connection = new TerminalConnection(
    {
      async write(url, payload) {
        actions.push(payload.action);
        return { id: "pty", status: "open" };
      },
      async read() {
        throw new Error("offline");
      },
    },
    "/remote/",
    () => {},
    (status) => statuses.push(status)
  );
  await connection.open("computer", 80, 24);
  await flush();
  assert.deepEqual(statuses, ["connecting", "open", "error"]);
  assert.equal(actions.at(-1), "close");
});

function nodes(tree) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}

const FileView = () => null;
const TerminalView = () => null;
function renderRoot(devices, selected = "", terminal = "", error = undefined, hasData = true, activeResults = []) {
  let cursor = 0;
  const states = [selected, terminal];
  const mutations = [];
  const { RemoteDiagnostics } = load("./root.tsx", {
    react: {
      ...React,
      useState: () => {
        const index = cursor++;
        return [states[index], (value) => mutations.push([index, value])];
      },
    },
    "react-router": { useParams: () => ({ workspaceSlug: "test" }), useSearchParams: () => [new URLSearchParams()] },
    swr: {
      default: () => ({
        data: hasData ? { results: devices, active_results: activeResults, can_manage: true } : undefined,
        error,
        mutate() {},
      }),
    },
    "lucide-react": { Monitor: () => null, RefreshCw: () => null },
    "@/components/quality/api": { qualityApi: {}, errorMessage: String },
    "@/components/settings/content-wrapper": { SettingsContentWrapper: () => null },
    "./agent-panel": { AgentPanel: () => null },
    "./file-panel": { FilePanel: FileView },
    "./terminal-panel": { TerminalPanel: TerminalView },
    "./types": types,
    "./feedback-picker": { FeedbackPicker: () => null },
    "./remote-feedback-history": { RemoteFeedbackHistory: () => null },
  });
  return { tree: RemoteDiagnostics(), mutations, FileView, TerminalView };
}

const device = {
  id: "computer",
  name: "现场电脑",
  username: "operator",
  hostname: "robot-01",
  ip_address: "10.0.0.195",
  online: true,
  can_connect: true,
  capabilities: {},
};

test("device card displays identity and selecting it does not open a shell implicitly", () => {
  const { tree, mutations } = renderRoot([device]);
  const card = nodes(tree).find((node) => node.type === "button" && node.props["aria-pressed"] === false);
  card.props.onClick();
  assert.deepEqual(mutations, [
    [0, "computer"],
    [1, ""],
  ]);
  const texts = JSON.stringify(tree);
  assert.match(texts, /operator/);
  assert.match(texts, /robot-01/);
  assert.match(texts, /在线/);
  const title = nodes(card).find((node) => node.type === "h2");
  assert.equal(title.props.children.join(""), "operator@10.0.0.195");
});

test("missing collector IP stays unknown instead of substituting hostname or loopback", () => {
  const { tree } = renderRoot([{ ...device, ip_address: undefined }]);
  const card = nodes(tree).find((node) => node.type === "button" && node.props["aria-pressed"] === false);
  const title = nodes(card).find((node) => node.type === "h2");
  assert.equal(title.props.children.join(""), "operator@IP待确认");
  assert.doesNotMatch(JSON.stringify(title), /127\.0\.0\.1|robot-01/);
});

test("cached device refresh error keeps selected file and terminal sessions mounted with a retry notice", () => {
  const { tree } = renderRoot([device], device.id, device.id, new Error("502"));
  assert.equal(nodes(tree).filter((node) => node.type === FileView).length, 1);
  assert.equal(nodes(tree).filter((node) => node.type === TerminalView).length, 1);
  assert.match(JSON.stringify(tree), /设备状态刷新失败，稍后重试/);
  const refresh = nodes(tree).find(
    (node) => node.type === "button" && JSON.stringify(node.props.children).includes("刷新设备")
  );
  assert.equal(refresh.props.disabled, undefined);
});

test("collector DHCP refresh preserves station selection and terminal React key", () => {
  const before = renderRoot([device], device.id, device.id);
  const after = renderRoot([{ ...device, ip_address: "10.0.0.196" }], device.id, device.id);
  const original = nodes(before.tree).find((node) => node.type === TerminalView);
  const updated = nodes(after.tree).find((node) => node.type === TerminalView);
  assert.equal(original.key, updated.key);
  assert.equal(updated.props.device.id, device.id);
  assert.equal(updated.props.device.ip_address, "10.0.0.196");
  assert.deepEqual(after.mutations, []);
});

test("no cached directory does not grant access and explicit removal or revoked connection closes terminal", () => {
  const first = renderRoot([], device.id, device.id, new Error("initial error"), false);
  assert.equal(
    nodes(first.tree).some((node) => node.type === first.FileView || node.type === first.TerminalView),
    false
  );
  assert.match(JSON.stringify(first.tree), /initial error/);
  for (const devices of [[], [{ ...device, can_connect: false }]]) {
    const next = renderRoot(devices, device.id, device.id);
    assert.equal(
      nodes(next.tree).some((node) => node.type === next.TerminalView),
      false
    );
    if (devices.length)
      assert.equal(
        nodes(next.tree).find((node) => node.type === "button" && node.props.children === "打开终端").props.disabled,
        true
      );
  }
});

test("remote diagnosis uses the workspace page and legacy settings page only redirects", () => {
  const routes = readFileSync(new URL("../../../app/routes/core.ts", import.meta.url), "utf8");
  const route = routes.indexOf('":workspaceSlug/remote-diagnostics"');
  assert.ok(route > 0 && route < routes.indexOf("// WORKSPACE SETTINGS"));
  assert.match(routes, /\(projects\)\/remote-diagnostics\/page\.tsx/);
  const oldPage = readFileSync(
    new URL(
      "../../../app/(all)/[workspaceSlug]/(settings)/settings/(management)/remote-diagnostics/page.tsx",
      import.meta.url
    ),
    "utf8"
  );
  assert.match(oldPage, /<Navigate replace/);
  assert.doesNotMatch(oldPage, /<RemoteDiagnostics/);
});

test("offline and unauthorized devices cannot open a terminal", () => {
  for (const overrides of [{ online: false }, { can_connect: false }]) {
    const { tree } = renderRoot([{ ...device, ...overrides }], "computer");
    const button = nodes(tree).find((node) => node.type === "button" && node.props.children === "打开终端");
    assert.equal(button.props.disabled, true);
  }
});

test("Agent diagnosis starts only after explicit action and includes the selected original feedback", async () => {
  let cursor = 0;
  const states = [{ id: "feedback-1", code: "FB-1", title: "现场原始反馈" }, "采集无画面", false, null, "", 1];
  const calls = [];
  const { AgentPanel } = load("./agent-panel.tsx", {
    react: {
      ...React,
      useState: () => [states[cursor++], () => {}],
      useRef: (initial) => ({ current: initial }),
      useEffect() {},
    },
    swr: {
      default: (url) => ({
        data: url?.includes("collaboration")
          ? []
          : { results: [{ id: "feedback-1", code: "FB-1", title: "现场原始反馈" }] },
        mutate() {},
      }),
    },
    "@/components/quality/api": {
      qualityApi: {
        async write(url, body) {
          calls.push({ url, body });
          return { id: "run-1", status: "running" };
        },
      },
      errorMessage: String,
    },
    "@/components/quality/shared": { fieldClass: "field" },
    "./types": types,
    "./feedback-picker": { FeedbackPicker: () => null },
    "./remote-feedback-history": { RemoteFeedbackHistory: () => null },
  });
  const tree = AgentPanel({ device });
  assert.equal(calls.length, 0);
  const button = nodes(tree).find((node) => node.type === "button" && node.props.children === "开始处理");
  assert.equal(button.props.disabled, false);
  button.props.onClick();
  await flush();
  assert.deepEqual(calls, [
    {
      url: "/api/quality-auth/remote-diagnostics/agent-runs/",
      body: { device_id: "computer", defect_id: "feedback-1", mode: "repair", problem: "采集无画面" },
    },
  ]);
});

test("Agent diagnosis requires original feedback and does not submit without one", async () => {
  let cursor = 0;
  const states = [undefined, "采集无画面", false, null, "", 1];
  let submissions = 0;
  const { AgentPanel } = load("./agent-panel.tsx", {
    react: {
      ...React,
      useState: () => [states[cursor++], () => {}],
      useRef: (initial) => ({ current: initial }),
      useEffect() {},
    },
    swr: { default: (url) => ({ data: url ? { results: [] } : undefined, mutate() {} }) },
    "@/components/quality/api": {
      qualityApi: {
        async write() {
          submissions++;
        },
      },
      errorMessage: String,
    },
    "@/components/quality/shared": { fieldClass: "field" },
    "./types": types,
    "./feedback-picker": { FeedbackPicker: () => null },
    "./remote-feedback-history": { RemoteFeedbackHistory: () => null },
  });
  const tree = AgentPanel({ device });
  const button = nodes(tree).find((node) => node.type === "button" && node.props.children === "开始处理");
  assert.equal(button.props.disabled, true);
  assert.equal(
    nodes(tree).some((node) => node.type === "select"),
    false
  );
  button.props.onClick();
  await flush();
  assert.equal(submissions, 0);
  assert.match(JSON.stringify(tree), /原始反馈/);
});

test("terminal bundles official CSS so measurement helpers and hidden input stay invisible", () => {
  const source = readFileSync(new URL("./terminal-panel.tsx", import.meta.url), "utf8");
  const root = readFileSync(new URL("../../../app/root.tsx", import.meta.url), "utf8");
  assert.match(root, /import terminalStyles from "@xterm\/xterm\/css\/xterm.css\?url"/);
  assert.match(root, /monoFontStyles, terminalStyles/);
  assert.match(source, /minimumContrastRatio: 4.5/);
});

test("terminal fit host excludes outer padding and fits again after fonts load", () => {
  const source = readFileSync(new URL("./terminal-panel.tsx", import.meta.url), "utf8");
  assert.match(source, /ref=\{containerRef\}[^>]*className="h-full min-w-0"/);
  assert.match(source, /document.fonts.ready/);
});

test("device navigation is paged and independent from the active terminal pane", () => {
  const { tree } = renderRoot([device], device.id, device.id);
  const list = nodes(tree).find((n) => n.props?.["aria-label"] === "采集电脑列表");
  const work = nodes(tree).find((n) => n.props?.["aria-label"] === "当前电脑操作");
  assert.ok(list && work);
  assert.equal(
    nodes(list).some((n) => n.type === TerminalView),
    false
  );
  assert.equal(nodes(work).filter((n) => n.type === TerminalView).length, 1);
  const size = nodes(list).find((n) => n.props?.["aria-label"] === "每页电脑数量");
  assert.equal(size.props.value, 6);
  assert.ok(nodes(list).some((n) => n.props?.["aria-label"] === "搜索采集电脑"));
  assert.ok(nodes(list).some((n) => n.props?.["aria-label"] === "设备在线状态"));
});

test("paging away from the selected computer preserves its terminal and files via current authorized pin", () => {
  const other = { ...device, id: "other", username: "second" };
  const before = renderRoot([device], device.id, device.id);
  const after = renderRoot([other], device.id, device.id, undefined, true, [device]);
  const initialTerminal = nodes(before.tree).find((n) => n.type === TerminalView);
  const pagedTerminal = nodes(after.tree).find((n) => n.type === TerminalView);
  assert.equal(pagedTerminal.key, initialTerminal.key);
  assert.equal(pagedTerminal.props.device.id, device.id);
  assert.equal(nodes(after.tree).find((n) => n.type === FileView).props.device.id, device.id);
  const revoked = renderRoot([other], device.id, device.id, undefined, true, []);
  assert.equal(nodes(revoked.tree).filter((n) => n.type === TerminalView).length, 0);
});

test("live stream sends ordered input with acknowledgements and no HTTP polling after upgrade", async () => {
  const sockets = [];
  const originalWindow = globalThis.window,
    originalSocket = globalThis.WebSocket;
  class Socket {
    static OPEN = 1;
    readyState = 1;
    bufferedAmount = 0;
    messages = [];
    constructor(url) {
      this.url = url;
      sockets.push(this);
      setImmediate(() => this.onopen?.());
    }
    addEventListener(name, callback) {
      this["on" + name] = callback;
    }
    send(raw) {
      const message = JSON.parse(raw);
      this.messages.push(message);
      setImmediate(() => this.onmessage?.({ data: JSON.stringify({ type: "ack", seq: message.seq }) }));
    }
    close() {
      this.readyState = 3;
      this.onclose?.();
    }
  }
  globalThis.window = { location: { origin: "http://platform.test" } };
  globalThis.WebSocket = Socket;
  const output = [],
    requests = [];
  try {
    const connection = new TerminalConnection(
      {
        read: async () => {
          throw new Error("must not poll after upgrade");
        },
        write: async (url, body) => {
          requests.push(body.action);
          return { id: "live", status: "open" };
        },
      },
      "/remote/",
      (bytes) => output.push(...bytes),
      () => {}
    );
    await connection.open("computer", 80, 24);
    assert.match(String(sockets[0].url), /ws:\/\/platform.test\/remote\/terminal-stream\/live\//);
    connection.input("cd 中文\r");
    await flushInputFrame();
    await flush();
    assert.deepEqual(requests, ["open"]);
    assert.equal(new TextDecoder().decode(decodeTerminalOutput(sockets[0].messages[0].data)), "cd 中文\r");
    sockets[0].onmessage({
      data: JSON.stringify({
        type: "output",
        status: "open",
        cursor: 1,
        events: [{ seq: 1, data: encodeTerminalInput("ok") }],
      }),
    });
    assert.equal(new TextDecoder().decode(Uint8Array.from(output)), "ok");
    connection.dispose();
    await flush();
    assert.equal(requests.at(-1), "close");
  } finally {
    globalThis.window = originalWindow;
    globalThis.WebSocket = originalSocket;
  }
});

test("slow server acknowledgements keep input bounded and coalesce queued keys", async () => {
  const oldWindow = globalThis.window,
    oldSocket = globalThis.WebSocket,
    sockets = [];
  class Socket {
    static OPEN = 1;
    readyState = 1;
    bufferedAmount = 0;
    messages = [];
    constructor() {
      sockets.push(this);
      setImmediate(() => this.onopen?.());
    }
    addEventListener(name, fn) {
      this["on" + name] = fn;
    }
    send(raw) {
      this.messages.push(JSON.parse(raw));
    }
    close() {
      this.onclose?.();
    }
  }
  globalThis.window = { location: { origin: "http://platform.test" } };
  globalThis.WebSocket = Socket;
  try {
    const c = new TerminalConnection(
      { read: () => new Promise(() => {}), write: async () => ({ id: "bounded", status: "open" }) },
      "/remote/",
      () => {},
      () => {}
    );
    await c.open("computer", 80, 24);
    c.input("c");
    await flushInputFrame();
    c.input("d");
    await flushInputFrame();
    assert.equal(sockets[0].messages.length, 1, "do not flood a slower receiver with per-key frames");
    sockets[0].onmessage({ data: JSON.stringify({ type: "ack", seq: 1 }) });
    await flush();
    assert.equal(sockets[0].messages.length, 2);
    assert.deepEqual(
      sockets[0].messages.map((m) => m.seq),
      [1, 2]
    );
    c.dispose();
  } finally {
    globalThis.window = oldWindow;
    globalThis.WebSocket = oldSocket;
  }
});
