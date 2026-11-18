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

function renderRoot(devices, selected = "", terminal = "") {
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
    swr: { default: () => ({ data: { results: devices, can_manage: true }, mutate() {} }) },
    "lucide-react": { Monitor: () => null, RefreshCw: () => null },
    "@/components/quality/api": { qualityApi: {}, errorMessage: String },
    "@/components/settings/content-wrapper": { SettingsContentWrapper: () => null },
    "./agent-panel": { AgentPanel: () => null },
    "./file-panel": { FilePanel: () => null },
    "./terminal-panel": { TerminalPanel: () => null },
    "./types": types,
  });
  return { tree: RemoteDiagnostics(), mutations };
}

const device = {
  id: "computer",
  name: "现场电脑",
  username: "operator",
  hostname: "robot-01",
  online: true,
  can_connect: true,
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
  assert.equal(title.props.children, "operator");
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
  const states = ["", "", 1, "needs_attention", "feedback-1", "采集无画面", false, null, "", 1];
  const calls = [];
  const { AgentPanel } = load("./agent-panel.tsx", {
    react: {
      ...React,
      useState: () => [states[cursor++], () => {}],
      useRef: () => ({ current: true }),
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
  });
  const tree = AgentPanel({ device });
  assert.equal(calls.length, 0);
  const button = nodes(tree).find((node) => node.type === "button" && node.props.children === "开始诊断");
  assert.equal(button.props.disabled, false);
  button.props.onClick();
  await flush();
  assert.deepEqual(calls, [
    {
      url: "/api/quality-auth/remote-diagnostics/agent-runs/",
      body: { device_id: "computer", defect_id: "feedback-1", problem: "采集无画面" },
    },
  ]);
});

test("Agent diagnosis requires original feedback and does not submit without one", async () => {
  let cursor = 0;
  const states = ["", "", 1, "needs_attention", "", "采集无画面", false, null, "", 1];
  let submissions = 0;
  const { AgentPanel } = load("./agent-panel.tsx", {
    react: {
      ...React,
      useState: () => [states[cursor++], () => {}],
      useRef: () => ({ current: true }),
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
  });
  const tree = AgentPanel({ device });
  const button = nodes(tree).find((node) => node.type === "button" && node.props.children === "开始诊断");
  assert.equal(button.props.disabled, true);
  assert.equal(nodes(tree).find((node) => node.type === "select" && node.props.required).props.required, true);
  button.props.onClick();
  await flush();
  assert.equal(submissions, 0);
  assert.match(JSON.stringify(tree), /当前筛选没有匹配反馈/);
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
  assert.match(source, /ref=\{containerRef\}[^\n]*className="h-full min-w-0"/);
  assert.match(source, /document.fonts.ready/);
});
