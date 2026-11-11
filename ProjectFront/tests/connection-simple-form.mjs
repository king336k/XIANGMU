import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const React = require("react");
const Field = () => null;
const Modal = () => null;

function renderForm(kind = "data_platform", editing = null) {
  let cursor = 0;
  const state = [editing, undefined, kind];
  const exports = {};
  const source = readFileSync(new URL("../core/components/quality/connection-settings.tsx", import.meta.url), "utf8");
  const mocks = {
    react: { ...React, useState: () => [state[cursor++], () => {}] },
    swr: {
      default: () => ({ data: { can_configure: true, results: [], ota_directories_enabled: true }, mutate() {} }),
    },
    "react/jsx-runtime": require("react/jsx-runtime"),
    "@plane/ui": { Button: () => null },
    "./api": { qualityApi: {}, errorMessage: (e) => e.message },
    "./shared": { Field, Modal, fieldClass: "field" },
    "./legacy-directory-panel": { LegacyDirectoryPanel: () => null },
    "./connection-form-data": helpers(),
  };
  new Function(
    "require",
    "exports",
    ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((name) => mocks[name], exports);
  const tree = exports.ConnectionSettings({ endpoint: "/api/quality-auth/connections/" });
  function fields(node, advanced = false) {
    if (!node || typeof node !== "object") return [];
    if (Array.isArray(node)) return node.flatMap((child) => fields(child, advanced));
    const inside = advanced || node.type === "details";
    return [
      ...(node.type === Field ? [{ label: node.props.label, advanced: inside }] : []),
      ...fields(node.props?.children, inside),
    ];
  }
  return fields(tree);
}

function helpers() {
  const exports = {};
  new Function(
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/quality/connection-form-data.ts", import.meta.url), "utf8"),
      {
        compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
      }
    ).outputText
  )(exports);
  return exports;
}

test("new connection leaves internal identity and defaults to the server", () => {
  const { connectionPayload } = helpers();
  const form = new FormData();
  form.set("kind", "data_platform");
  form.set("base_url", "http://10.1.2.3:6324");
  form.set("service_token", "synthetic");
  const payload = connectionPayload(form, null, false);
  assert.equal(payload.kind, "data_platform");
  assert.equal(payload.base_url, "http://10.1.2.3:6324");
  assert.equal(payload.service_token, "synthetic");
  for (const name of [
    "source_instance",
    "bridge_key_id",
    "bridge_audience",
    "portal_url",
    "directory_auth",
    "login_role_map",
  ])
    assert.equal(name in payload, false, name);
});

test("editing a basic field omits advanced values rather than clearing them", () => {
  const { connectionPayload } = helpers();
  const form = new FormData();
  form.set("kind", "data_platform");
  form.set("base_url", "https://new.example");
  const payload = connectionPayload(form, { source_instance: "original", kind: "data_platform" }, false);
  assert.equal(payload.source_instance, "original");
  for (const name of [
    "service_token",
    "bridge_secret",
    "directory_auth",
    "directory_key_id",
    "portal_url",
    "login_enabled",
    "login_auto_provision",
  ])
    assert.equal(name in payload, false, name);
});

test("explicit login and clear switches survive unchecked state", () => {
  const { connectionPayload } = helpers();
  const form = new FormData();
  form.set("kind", "data_platform");
  form.set("base_url", "https://p.example");
  form.set("login_options_present", "1");
  form.set("clear_token", "on");
  const payload = connectionPayload(form, { source_instance: "original", kind: "data_platform" }, false);
  assert.equal(payload.login_enabled, false);
  assert.equal(payload.login_auto_provision, false);
  assert.equal(payload.clear_token, true);
});

test("basic connection form has only kind address and credential outside advanced settings", () => {
  const source = readFileSync(new URL("../core/components/quality/connection-settings.tsx", import.meta.url), "utf8");
  assert.match(source, /高级设置/);
  assert.match(source, /kind === "legacy_hub"/);
  assert.doesNotMatch(source, /首次登录岗位策略|来源实例名称 \*/);
  assert.match(source, /connectionPayload\(form, editing/);
});

test("rendered data-platform form only asks three basic fields and has no legacy directory fields", () => {
  const fields = renderForm();
  assert.deepEqual(
    fields.filter((field) => !field.advanced).map((field) => field.label),
    ["平台类型", "服务器地址 *", "访问凭据"]
  );
  assert.equal(
    fields.some((field) => field.label === "来源服务用户编号"),
    false
  );
  assert.equal(fields.find((field) => field.label === "连接标识").advanced, true);
});

test("rendered fields follow platform type and preserve optional existing credentials", () => {
  const legacy = renderForm("legacy_hub");
  assert.equal(
    legacy.some((field) => field.label === "来源服务用户编号"),
    true
  );
  assert.equal(
    legacy.some((field) => field.label === "接收方标识"),
    false
  );
  const existing = renderForm("data_platform", { source_instance: "old", kind: "data_platform", token_present: true });
  assert.equal(
    existing.some((field) => field.label === "访问凭据（留空保留）" && !field.advanced),
    true
  );
  const ota = renderForm("ota");
  assert.equal(
    ota.some((field) => field.label === "安装包目录（每行一个） *" && !field.advanced),
    true
  );
});
