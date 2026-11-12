import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript");
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
function form() {
  let index = 0;
  const states = [],
    writes = [];
  const exp = {};
  new Function(
    "crypto",
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL("../core/components/quality/case-form.tsx", import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )(
    {},
    (id) => {
      if (id === "react")
        return {
          useState: (initial) => {
            const n = index++;
            if (!(n in states)) states[n] = typeof initial === "function" ? initial() : initial;
            return [
              states[n],
              (value) => {
                states[n] = value;
              },
            ];
          },
          useMemo: (fn) => fn(),
        };
      if (id === "react/jsx-runtime" || id === "uuid") return require(id);
      if (id === "swr") return { default: () => ({}) };
      if (id === "./types") return { priorityNames: { medium: "中" } };
      if (id === "./api")
        return {
          qualityApi: {
            write: async (...args) => {
              writes.push(args);
            },
          },
        };
      return new Proxy({}, { get: () => () => null });
    },
    exp
  );
  return {
    states,
    writes,
    render() {
      index = 0;
      return exp.CaseForm({ base: "/q/", context: { can_write: true }, onClose() {}, onSaved: async () => {} });
    },
  };
}
function nodes(t) {
  return !t || typeof t !== "object" ? [] : Array.isArray(t) ? t.flatMap(nodes) : [t, ...nodes(t.props?.children)];
}
test("HTTP内网缺少crypto.randomUUID时可以新建用例、添加步骤并保存", async () => {
  const h = form();
  let tree = h.render();
  assert.equal(tree.props.title, "新建测试用例");
  assert.equal(h.states[0].length, 1);
  assert.match(h.states[0][0].localId, uuid);
  nodes(tree)
    .find((n) => n.props?.children === "添加步骤")
    .props.onClick();
  tree = h.render();
  assert.equal(h.states[0].length, 2);
  assert.notEqual(h.states[0][0].localId, h.states[0][1].localId);
  await tree.props.onSubmit(new Map([["title", "HTTP新建用例"]]));
  assert.equal(h.writes[0][0], "/q/cases/");
  assert.equal(h.writes[0][1].steps.length, 2);
});

test("浏览器uuid fallback不依赖secure-context randomUUID", async () => {
  const { webcrypto } = await import("node:crypto");
  const moduleUrl = new URL("../node_modules/uuid/dist/v4.js", import.meta.url);
  const original = Object.getOwnPropertyDescriptor(globalThis, "crypto");
  try {
    Object.defineProperty(globalThis, "crypto", {
      configurable: true,
      value: { getRandomValues: webcrypto.getRandomValues.bind(webcrypto) },
    });
    const { default: v4 } = await import(moduleUrl.href);
    assert.match(v4(), uuid);
  } finally {
    if (original) Object.defineProperty(globalThis, "crypto", original);
    else delete globalThis.crypto;
  }
});

test("HTTP执行表单重渲染和失败重试保留同一request_id", async () => {
  let index = 0;
  const states = [],
    writes = [],
    exp = {};
  new Function(
    "crypto",
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/quality/execution-form.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }
    ).outputText
  )(
    {},
    (id) => {
      if (id === "react")
        return {
          useState: (initial) => {
            const n = index++;
            if (!(n in states)) states[n] = typeof initial === "function" ? initial() : initial;
            return [
              states[n],
              (value) => {
                states[n] = value;
              },
            ];
          },
          useMemo: (fn) => fn(),
        };
      if (id === "react/jsx-runtime" || id === "uuid") return require(id);
      if (id === "./types") return { reasonNames: {}, resultNames: { passed: "通过" } };
      if (id === "./api")
        return {
          qualityApi: {
            write: async (...args) => {
              writes.push(args);
              if (writes.length === 1) throw Error("network");
            },
          },
        };
      return new Proxy({}, { get: () => () => null });
    },
    exp
  );
  const render = () => {
    index = 0;
    return exp.ExecutionForm({
      base: "/q/",
      plan: {},
      item: { id: "i", revision: { snapshot: { steps: [{ action: "执行", expected: "通过" }] } } },
      onClose() {},
      onSaved: async () => {},
    });
  };
  await assert.rejects(render().props.onSubmit(new Map()), /network/);
  await render().props.onSubmit(new Map());
  assert.match(writes[0][1].request_id, uuid);
  assert.equal(writes[0][1].request_id, writes[1][1].request_id);
});

test("HTTP问答网络失败后同一草稿重试保留request_id", async () => {
  let index = 0,
    refIndex = 0;
  const states = [],
    refs = [],
    writes = [],
    exp = {};
  const stateExp = {};
  new Function(
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/knowledge/assistant-state.ts", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS } }
    ).outputText
  )(stateExp);
  new Function(
    "crypto",
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/knowledge/assistant-use-chat.ts", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }
    ).outputText
  )(
    {},
    (id) => {
      if (id === "react")
        return {
          useState: (initial) => {
            const n = index++;
            if (!(n in states)) states[n] = typeof initial === "function" ? initial() : initial;
            return [
              states[n],
              (value) => {
                states[n] = typeof value === "function" ? value(states[n]) : value;
              },
            ];
          },
          useRef: (initial) => {
            const n = refIndex++;
            return refs[n] ?? (refs[n] = { current: initial });
          },
        };
      if (id === "uuid") return require(id);
      if (id === "axios") return { isAxiosError: () => false };
      if (id === "./assistant-state") return stateExp;
      if (id === "swr")
        return {
          default: (url) => ({ data: url?.endsWith("status/") ? { configured: true } : [], mutate: async () => {} }),
          useSWRConfig: () => ({ mutate: async () => {} }),
        };
      if (id === "@/components/quality/api")
        return {
          qualityApi: {
            write: async (...args) => {
              writes.push(args);
              throw Error("network");
            },
          },
          errorMessage: String,
        };
      throw Error(id);
    },
    exp
  );
  const render = () => {
    index = refIndex = 0;
    return exp.useAssistantChat("/knowledge/", true);
  };
  render().setDraft("如何重试");
  await render().send();
  await render().send();
  assert.equal(writes.length, 2);
  assert.match(writes[0][1].request_id, uuid);
  assert.equal(writes[0][1].request_id, writes[1][1].request_id);
});
