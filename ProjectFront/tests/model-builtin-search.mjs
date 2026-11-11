import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
const stubs = new Map();
function stub(name) {
  if (!stubs.has(name)) stubs.set(name, () => null);
  return stubs.get(name);
}
const configured = {
  configured: true,
  key_present: true,
  model: "chat-model",
  base_url: "https://provider.example/v1",
  can_configure: true,
  semantic_enabled: true,
  embedding_model: "builtin-bge",
  embedding_base_url: "http://internal:8080/v1",
  embedding_key_present: true,
  semantic: { source: "builtin", managed: true, enabled: true, configured: true, status: "ready" },
};
function harness(data = configured) {
  let cursor = 0;
  const state = [],
    writes = [];
  const exports = {};
  new Function(
    "require",
    "exports",
    "FormData",
    ts.transpileModule(
      readFileSync(new URL("../core/components/knowledge/model-settings.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }
    ).outputText
  )(
    (id) => {
      if (id === "react")
        return {
          ...React,
          useState(initial) {
            const at = cursor++;
            if (!(at in state)) state[at] = initial;
            return [
              state[at],
              (value) => {
                state[at] = value;
              },
            ];
          },
        };
      if (id === "react/jsx-runtime") return require(id);
      if (id === "swr") return { default: () => ({ data, mutate: async () => {} }) };
      if (id === "../quality/api")
        return { qualityApi: { write: async (...args) => writes.push(args) }, errorMessage: String };
      return new Proxy({}, { get: (_, key) => (key === "fieldClass" ? "field" : stub(key)) });
    },
    exports,
    class {
      constructor(values) {
        this.values = values;
      }
      get(key) {
        return this.values[key] ?? null;
      }
    }
  );
  return {
    writes,
    render() {
      cursor = 0;
      return exports.ModelSettings({ base: "/knowledge/" });
    },
  };
}
function nodes(tree) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
const words = (tree) =>
  nodes(tree)
    .flatMap((node) => [node.props?.children].flat())
    .filter((x) => typeof x === "string")
    .join("");
const submit = (tree, values = {}) =>
  nodes(tree)
    .find((node) => node.type === "form")
    .props.onSubmit({
      preventDefault() {},
      currentTarget: { model: "updated-chat", base_url: "https://chat.example/v1", ...values },
    });
test("普通保存只写聊天连接，保留既有内置或外部向量设置和密钥", async () => {
  await Promise.all(
    ["builtin", "external", "shared"].map(async (source) => {
      const h = harness({ ...configured, semantic: { ...configured.semantic, source } });
      await submit(h.render());
      assert.deepEqual(h.writes[0], [
        "/knowledge/configuration/",
        {
          model: "updated-chat",
          base_url: "https://chat.example/v1",
          api_key: "",
          clear_key: false,
        },
        "patch",
      ]);
    })
  );
});
test("日常表单只有聊天字段，内置检索显示只读就绪且说明无需另配", () => {
  const tree = harness().render();
  assert.match(words(tree), /内置知识检索.*已就绪/);
  assert.match(words(tree), /平台部署管理.*无需重复设置/);
  assert.doesNotMatch(words(tree), /沿用问答模型|启用语义检索/);
  assert.equal(
    nodes(tree).filter((node) => node.type === "input" && node.props.name?.startsWith("embedding_")).length,
    0
  );
  assert.equal(
    nodes(tree).some((node) => node.type === "details"),
    true
  );
});
test("向量未就绪真实显示，不把已配置聊天误报为检索已就绪", () => {
  const tree = harness({
    ...configured,
    semantic: { ...configured.semantic, configured: false, status: "unconfigured" },
  }).render();
  assert.match(words(tree), /内置知识检索.*未就绪/);
});
test("外部与旧共享检索明确区分，未知或缺失来源不冒称内置已就绪", () => {
  const external = harness({ ...configured, semantic: { ...configured.semantic, source: "external" } }).render();
  assert.match(words(external), /外部知识检索.*已就绪/);
  const shared = harness({ ...configured, semantic: { ...configured.semantic, source: "shared" } }).render();
  assert.match(words(shared), /知识检索.*待接通/);
  const unknown = harness({ ...configured, semantic: { configured: true, status: "ready" } }).render();
  assert.doesNotMatch(words(unknown), /内置知识检索.*已就绪/);
});
test("高级配置只有显式选择外部模式才提交独立向量连接", async () => {
  const h = harness();
  let tree = h.render();
  nodes(tree)
    .find((node) => node.type === "details")
    .props.onToggle({ currentTarget: { open: true } });
  tree = h.render();
  const mode = nodes(tree).find((node) => node.type === "select" && node.props.name === "embedding_mode");
  assert.ok(mode);
  mode.props.onChange({ target: { value: "external" } });
  tree = h.render();
  const url = nodes(tree).find((node) => node.type === "input" && node.props.name === "embedding_base_url");
  assert.equal(url.props.required, true);
  await submit(tree, {
    embedding_model: "external-embed",
    embedding_base_url: "https://embed.example/v1",
    embedding_api_key: "",
    clear_embedding_key: "on",
  });
  assert.deepEqual(h.writes[0][1], {
    model: "updated-chat",
    base_url: "https://chat.example/v1",
    api_key: "",
    clear_key: false,
    embedding_mode: "external",
    semantic_enabled: true,
    embedding_model: "external-embed",
    embedding_base_url: "https://embed.example/v1",
    embedding_api_key: "",
    clear_embedding_key: true,
  });
  await submit(h.render());
  assert.equal("embedding_mode" in h.writes[1][1], false);
});
test("高级区域关闭后普通保存不提交向量字段，外部地址为空时不回退聊天服务", async () => {
  const h = harness();
  let tree = h.render();
  nodes(tree)
    .find((node) => node.type === "details")
    .props.onToggle({ currentTarget: { open: true } });
  tree = h.render();
  nodes(tree)
    .find((node) => node.type === "select")
    .props.onChange({ target: { value: "external" } });
  tree = h.render();
  await submit(tree, { embedding_model: "embed" });
  assert.equal(h.writes.length, 0);
  assert.match(words(h.render()), /请填写外部向量模型和独立接口地址/);
  nodes(h.render())
    .find((node) => node.type === "details")
    .props.onToggle({ currentTarget: { open: false } });
  await submit(h.render());
  assert.equal("embedding_mode" in h.writes[0][1], false);
});
test("明确恢复内置检索只提交builtin模式，不携带旧外部地址或密钥", async () => {
  const h = harness({ ...configured, semantic: { ...configured.semantic, source: "external" } });
  let tree = h.render();
  nodes(tree)
    .find((node) => node.type === "details")
    .props.onToggle({ currentTarget: { open: true } });
  tree = h.render();
  const select = nodes(tree).find((node) => node.type === "select");
  assert.ok(nodes(select).some((node) => node.type === "option" && node.props.value === "builtin"));
  select.props.onChange({ target: { value: "builtin" } });
  await submit(h.render(), { embedding_base_url: "https://stale.example/v1" });
  assert.deepEqual(h.writes[0][1], {
    model: "updated-chat",
    base_url: "https://chat.example/v1",
    api_key: "",
    clear_key: false,
    embedding_mode: "builtin",
    semantic_enabled: true,
  });
});
test("清除聊天密钥不改向量密钥，非管理员无高级模式入口", async () => {
  const h = harness();
  await submit(h.render(), { clear_key: "on" });
  assert.equal(h.writes[0][1].clear_key, true);
  assert.equal("clear_embedding_key" in h.writes[0][1], false);
  const tree = harness({ ...configured, can_configure: false }).render();
  assert.equal(
    nodes(tree).some((node) => node.type === "select"),
    false
  );
  assert.match(words(tree), /内置知识检索/);
});
