import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const React = require("react");
const SnapshotSummary = () => null;
const source = readFileSync(new URL("../core/components/quality/deployment-snapshots.tsx", import.meta.url), "utf8");
const code = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
}).outputText;

function load(result, onRetry = () => {}) {
  const exports = {};
  const calls = [];
  let selection = "";
  const mocks = {
    react: {
      ...React,
      useState: (initial) => [
        selection || initial,
        (value) => {
          selection = value;
          calls.push(value);
        },
      ],
    },
    swr: {
      default: (url, fetcher) => {
        calls.push(url);
        assert.equal(typeof fetcher, "function");
        return { ...result, mutate: onRetry };
      },
    },
    "@plane/utils": { renderNumericDateTime: (value) => value },
    "@plane/ui": { Button: "button" },
    "lucide-react": { RotateCw: () => null },
    "./api": {
      qualityApi: { read: () => {} },
      errorMessage: (error) => error.message,
      attachmentDisplayName: (name) => name,
    },
  };
  new Function("require", "exports", code)((id) => mocks[id] ?? require(id), exports);
  const render = (compact, reportFileIds) =>
    exports.DeploymentSnapshots({ base: "/quality/", defectId: "defect-1", compact, reportFileIds });
  return { render, calls };
}

function walk(tree, predicate, found = []) {
  if (tree == null || typeof tree !== "object") return found;
  if (typeof tree.type === "function") return walk(tree.type(tree.props), predicate, found);
  if (predicate(tree)) found.push(tree);
  for (const child of [tree.props?.children].flat(Infinity)) walk(child, predicate, found);
  return found;
}

const component = {
  key: "daq",
  label: "DAQ（运行服务）",
  location: "host",
  status: "unavailable",
  version: "v1",
  branch: "main",
  commit: "a".repeat(40),
  commitMessage: "source commit",
  commitDate: "2026-11-10",
  builtAt: "",
  generatedAt: "2026-11-11",
  image: "",
  source: "version_info.yaml",
  reason: "版本文件缺失",
  submodules: [
    {
      key: "core",
      version: "v2",
      branch: "dev",
      commit: "b".repeat(40),
      commitMessage: "sub commit",
      commitDate: "2026-11-09",
    },
  ],
  omittedSubmodules: 0,
};
const row = (id, capturedAt, version) => ({
  file: { id, name: `feedback-${id}.json`, sha256: "f".repeat(64) },
  snapshot: {
    eventId: id,
    capturedAt,
    components: version ? [{ ...component, status: "available", version }] : [component],
    comparison: { status: "unknown", items: [] },
  },
});

test("overview renders uploaded history, provenance and real build timestamp only", () => {
  const { render, calls } = load({ data: { count: 2, results: [row("new", "2026-11-11"), row("old", "2026-11-10")] } });
  const tree = render(false);
  assert.equal(calls[0], "/quality/defects/defect-1/deployment-snapshots/");
  assert.equal(walk(tree, (node) => node.props?.["aria-label"] === "选择反馈版本快照").length, 1);
  walk(tree, (node) => node.props?.["aria-label"] === "选择反馈版本快照")[0].props.onChange({
    target: { value: "old" },
  });
  assert.equal(walk(render(false), (node) => node.props?.["aria-label"] === "选择反馈版本快照")[0].props.value, "old");
  const content = JSON.stringify(walk(tree, () => true));
  assert.match(content, /现场版本/);
  assert.equal(
    walk(
      tree,
      (node) => node.type === "details" && node.props.open && node.props.className === "platform-record-section"
    ).length,
    1
  );
  for (const label of ["组件", "版本 / 分支", "提交", "状态"]) {
    assert.equal(walk(tree, (node) => node.type === "span" && node.props.children === label).length, 1);
  }
  assert.match(content, /版本文件生成时间/);
  assert.doesNotMatch(content, /构建时间/);
  assert.match(content, /source commit/);
  assert.match(content, /SHA256/);
  assert.match(content, /缺失/);
});

test("compact diagnosis summary and empty state keep collection-time semantics", () => {
  const populated = load({ data: { count: 1, results: [row("new", "2026-11-11")] } }).render(true, ["new"]);
  assert.match(JSON.stringify(populated), /取证于/);
  assert.match(JSON.stringify(populated), /本报告材料中的版本快照/);
  assert.doesNotMatch(JSON.stringify(populated), /异常发生时/);
  const empty = load({ data: { count: 0, results: [] } }).render(false);
  assert.match(JSON.stringify(empty), /此反馈未记录版本快照/);
});

test("old report uses its source file rather than a newer upload", () => {
  const snapshots = load({
    data: { count: 2, results: [row("new", "2026-11-11", "v2"), row("old", "2026-11-10", "v1")] },
  });
  const linked = JSON.stringify(snapshots.render(true, ["old"]));
  assert.match(linked, /本报告材料中的版本快照/);
  assert.match(linked, /v1/);
  assert.doesNotMatch(linked, /v2/);
  const unlinked = JSON.stringify(snapshots.render(true, ["missing"]));
  assert.match(unlinked, /最新上传版本，尚未与当前报告关联/);
  assert.doesNotMatch(unlinked, /本报告材料中的版本快照/);
  assert.equal(
    walk(snapshots.render(true, ["old"]), (node) => node.props?.["aria-label"] === "选择反馈版本快照").length,
    0
  );
});

test("cached snapshot is hidden when revalidation reports an integrity error", () => {
  const tree = load({
    data: { count: 1, results: [row("new", "2026-11-11", "v2")] },
    error: Error("409 校验失败"),
  }).render(false);
  assert.equal(walk(tree, (node) => node.props?.role === "alert").length, 1);
  assert.doesNotMatch(JSON.stringify(tree), /取证于|SHA256|v2/);
});

function currentReportSummaryFileIds(sources, input) {
  const diagnosticsSource = readFileSync(
    new URL("../core/components/quality/diagnostics-panel.tsx", import.meta.url),
    "utf8"
  );
  const diagnosticsCode = ts.transpileModule(diagnosticsSource, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const exports = {};
  const current = {
    id: "old-report",
    status: "completed",
    created_at: "2026-11-10",
    result: { sources, input },
  };
  const mocks = {
    react: { ...React, useState: (value) => [value, () => {}] },
    swr: {
      default: (url) => ({
        data: url.endsWith("/status/")
          ? { configured: false }
          : { results: [current], count: 1, current_report: current },
        mutate() {},
      }),
    },
    "@plane/utils": { renderNumericDateTime: (value) => value },
    "@plane/ui": { Button: "button" },
    "lucide-react": new Proxy({}, { get: () => () => null }),
    "./api": { qualityApi: {}, errorMessage: String },
    "./types": { can: () => false },
    "./shared": { Paging: () => null },
    "./use-collection-pagination": { useCollectionPagination: () => ({ query: "page=1", paging: {} }) },
    "./deployment-snapshots": { DeploymentSnapshots: SnapshotSummary },
    "@/components/knowledge/assistant-markdown": { AssistantMarkdown: () => null },
  };
  new Function("require", "exports", diagnosticsCode)((id) => mocks[id] ?? require(id), exports);
  const tree = exports.DiagnosticsPanel({ base: "/quality/", defectId: "defect-1", context: {} });
  const summary = [tree.props.children].flat(Infinity).find((node) => node?.type === SnapshotSummary);
  return summary?.props.reportFileIds;
}

test("diagnosis panel binds summary to the current report's readable source file IDs", () => {
  assert.deepEqual(currentReportSummaryFileIds([{ file_id: "old", read_bytes: 20 }]), ["old"]);
});

test("unread or incomplete sources do not link a report to a matching snapshot", () => {
  const snapshots = load({ data: { count: 1, results: [row("old", "2026-11-10", "v1")] } });
  for (const entry of [
    { file_id: "old", read_bytes: 0 },
    { file_id: "old", read_bytes: 20, scan_incomplete: true },
  ]) {
    const fileIds = currentReportSummaryFileIds([entry], { files: ["old"] });
    assert.deepEqual(fileIds, []);
    const summary = JSON.stringify(snapshots.render(true, fileIds));
    assert.match(summary, /最新上传版本，尚未与当前报告关联/);
    assert.doesNotMatch(summary, /本报告材料中的版本快照/);
  }
});

test("error offers retry and loading is announced", async () => {
  let retries = 0;
  const error = load({ error: Error("读取失败") }, () => {
    retries += 1;
  });
  const tree = error.render(false);
  assert.equal(walk(tree, (node) => node.props?.role === "alert").length, 1);
  const retry = walk(tree, (node) => node.props?.["aria-label"] === "重试读取反馈版本")[0];
  retry.props.onClick();
  assert.equal(retries, 1);
  assert.equal(walk(load({ isLoading: true }).render(false), (node) => node.props?.role === "status").length, 1);
});
