import { reportSummary } from "./report-summary-fixture.js";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");

function load(name, mocks) {
  const exports = {};
  const source = readFileSync(new URL(`../core/components/quality/${name}`, import.meta.url), "utf8");
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  new Function("require", "exports", code)(
    (id) => (id === "./report-summary" ? reportSummary : mocks[id]) ?? require(id),
    exports
  );
  return exports;
}
function elements(tree, predicate, result = []) {
  if (!tree || typeof tree !== "object") return result;
  if (predicate(tree)) result.push(tree);
  for (const child of [tree.props?.children].flat(Infinity)) elements(child, predicate, result);
  return result;
}
function attachments(files, download = async () => {}) {
  const values = [];
  let cursor = 0;
  const mockReact = {
    ...React,
    useEffect() {},
    useState(initial) {
      const i = cursor++;
      if (!(i in values)) values[i] = initial;
      return [
        values[i],
        (value) => {
          values[i] = value;
        },
      ];
    },
  };
  const modules = load("defect-attachments.tsx", {
    react: mockReact,
    swr: { default: () => ({ data: files, mutate: async () => {} }) },
    "@plane/utils": { renderNumericDateTime: () => "" },
    "lucide-react": new Proxy({}, { get: () => () => null }),
    "@plane/ui": { Button: "button" },
    "./api": {
      qualityApi: { download },
      errorMessage: (error) => error.message,
      attachmentDisplayName: (name) =>
        load("api.ts", {
          axios: { isAxiosError: () => false },
          "@plane/constants": { API_BASE_URL: "" },
          "@/services/api.service": { APIService: Object },
        }).attachmentDisplayName(name),
    },
    "./attachment-viewer": { AttachmentViewer: () => null },
    "./inline-file-preview": { InlineFilePreview: () => null },
    "./types": { can: () => false },
    "react-dropzone": { useDropzone: () => ({ getRootProps: () => ({}), getInputProps: () => ({}), open() {} }) },
  });
  return () => {
    cursor = 0;
    return modules.DefectAttachments({ base: "/quality/", defectId: "defect-123", context: {} });
  };
}
const file = {
  id: "file-1",
  name: "diagnostic.zip",
  size: 20,
  source_system: "ENGRAM_DAQ",
  uploader: "collector",
  created_at: "",
};

test("有附件时提供一键打包，保留单文件下载；无附件不显示打包按钮", () => {
  for (const [files, count] of [
    [[], 0],
    [[file], 1],
  ]) {
    const tree = attachments(files)();
    assert.equal(elements(tree, (node) => node.props?.["aria-label"] === "一键打包下载").length, count);
    assert.equal(elements(tree, (node) => node.props?.["aria-label"] === "下载 diagnostic.zip").length, count);
  }
});
test("一键只请求当前缺陷ZIP，下载中禁用，结束后恢复", async () => {
  const calls = [];
  let resolve;
  const render = attachments([file], (...args) => {
    calls.push(args);
    return new Promise((done) => {
      resolve = done;
    });
  });
  const click = elements(render(), (node) => node.props?.["aria-label"] === "一键打包下载")[0];
  assert.ok(click, "应显示打包下载入口");
  click.props.onClick();
  assert.equal(elements(render(), (node) => node.props?.["aria-label"] === "一键打包下载")[0].props.disabled, true);
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], "/quality/defects/defect-123/attachments/download/");
  assert.ok(!/[\\/\r\n]/.test(calls[0][1]), "下载文件名不包含路径");
  resolve();
  await new Promise((done) => setImmediate(done));
  assert.equal(elements(render(), (node) => node.props?.["aria-label"] === "一键打包下载")[0].props.disabled, false);
});
test("打包失败显示后端原因并允许重试", async () => {
  const render = attachments([file], async () => {
    throw Error("部分附件尚未上传完整，请稍后重试。");
  });
  elements(render(), (node) => node.props?.["aria-label"] === "一键打包下载")[0]?.props.onClick();
  await new Promise((done) => setImmediate(done));
  const tree = render();
  const alert = elements(tree, (node) => node.props?.role === "alert")[0];
  assert.ok(alert, "应显示失败提示");
  assert.match(alert.props.children, /尚未上传完整/);
  assert.equal(elements(tree, (node) => node.props?.["aria-label"] === "一键打包下载")[0].props.disabled, false);
});

test("二进制下载的JSON错误能保留具体原因，拒绝时不生成下载", async () => {
  const response = {
    status: 409,
    data: new Blob([JSON.stringify({ detail: "附件校验失败，无法打包。" })], { type: "application/json" }),
  };
  const error = { isAxiosError: true, response };
  const { qualityApi, errorMessage } = load("api.ts", {
    axios: { isAxiosError: (value) => value?.isAxiosError === true },
    "@plane/constants": { API_BASE_URL: "" },
    "@/services/api.service": {
      APIService: class {
        async get() {
          throw error;
        }
      },
    },
  });
  await assert.rejects(
    qualityApi.download("/zip/", "附件.zip"),
    (value) => errorMessage(value) === "附件校验失败，无法打包。"
  );
});

function diagnostics(sources, download = async () => {}) {
  const values = [];
  let cursor = 0;
  const modules = load("diagnostics-panel.tsx", {
    react: {
      ...React,
      useRef: (initial) => ({ current: initial }),
      useEffect: () => {},
      useState(initial) {
        const i = cursor++;
        if (!(i in values)) values[i] = initial;
        return [
          values[i],
          (value) => {
            values[i] = value;
          },
        ];
      },
    },
    swr: {
      default: (url) => ({
        data: url.endsWith("/status/")
          ? { configured: true }
          : { count: 1, results: [{ id: "job", status: "completed", result: { sources } }] },
      }),
    },
    "@plane/utils": { renderNumericDateTime: () => "" },
    "@plane/ui": { Button: "button" },
    "lucide-react": new Proxy({}, { get: () => () => null }),
    "./api": { qualityApi: { download }, errorMessage: (error) => error.message },
    "./types": { can: () => false },
    "./use-collection-pagination": { useCollectionPagination: () => ({ query: "page=1", paging: {} }) },
    "./shared": { Paging: () => null },
    "./deployment-snapshots": { DeploymentSnapshots: () => null },
    "@/components/knowledge/assistant-markdown": { AssistantMarkdown: () => null },
  });
  return () => {
    cursor = 0;
    return modules.DiagnosticsPanel({ base: "/quality/", defectId: "defect-123", context: {} });
  };
}
test("诊断读取22个ZIP条目时只提供一次原附件打包请求，不逐条下载", async () => {
  const calls = [];
  let resolve;
  const render = diagnostics(
    Array.from({ length: 22 }, (_, index) => ({
      file_id: "same-zip",
      name: "diagnostic.zip",
      archive_entry: `log-${index}.txt`,
      read_bytes: 20,
    })),
    (...args) => {
      calls.push(args);
      return new Promise((done) => {
        resolve = done;
      });
    }
  );
  const buttons = elements(render(), (node) => node.props?.["aria-label"] === "一键打包下载");
  assert.equal(buttons.length, 1);
  assert.equal(buttons[0].props.title, "下载此缺陷全部原附件");
  buttons[0].props.onClick();
  assert.equal(elements(render(), (node) => node.props?.["aria-label"] === "一键打包下载")[0].props.disabled, true);
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], "/quality/defects/defect-123/attachments/download/");
  resolve();
  await new Promise((done) => setImmediate(done));
  assert.equal(elements(render(), (node) => node.props?.["aria-label"] === "一键打包下载")[0].props.disabled, false);
});
test("诊断页原附件打包错误就近显示，没有读取材料不展示该入口", async () => {
  assert.equal(elements(diagnostics([])(), (node) => node.props?.["aria-label"] === "一键打包下载").length, 0);
  const render = diagnostics([{ file_id: "a", name: "a.log" }], async () => {
    throw Error("附件损坏，无法打包。");
  });
  elements(render(), (node) => node.props?.["aria-label"] === "一键打包下载")[0]?.props.onClick();
  await new Promise((done) => setImmediate(done));
  const alert = elements(render(), (node) => node.props?.role === "alert")[0];
  assert.ok(alert);
  assert.match(alert.props.children, /附件损坏/);
});

test("generated evidence uses recognizable names for display and download without changing storage", async () => {
  const event = "0bfa1cad-5114-4aa1-b22c-bfb71fdfb7ab";
  await Promise.all(
    [
      [`feedback-${event}.json`, `feedback-version-${event}.json`],
      [`daq-diagnostics-${event}.zip`, `daq-diagnostic-logs-${event}.zip`],
    ].map(async ([original, expected]) => {
      const calls = [];
      const tree = attachments([{ ...file, name: original }], async (...args) => {
        calls.push(args);
      })();
      assert.ok(elements(tree, (node) => node.type === "p" && node.props.children === expected).length);
      elements(tree, (node) => node.props?.["aria-label"] === `下载 ${expected}`)[0].props.onClick();
      await new Promise((done) => setImmediate(done));
      assert.deepEqual(calls, [["/quality/files/file-1/download/", expected]]);
    })
  );
});
