import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
const stubCache = new Map();
const stub = (key) => {
  if (!stubCache.has(key)) stubCache.set(key, () => null);
  return stubCache.get(key);
};
function harness(api, file = "feishu-connection-select") {
  let cursor = 0;
  const writes = [];
  const state = [],
    effects = [],
    refs = [],
    pending = [],
    changed = [],
    statuses = [];
  const exp = {};
  new Function(
    "require",
    "exports",
    ts.transpileModule(readFileSync(new URL(`../core/components/quality/${file}.tsx`, import.meta.url), "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
  )((id) => {
    if (id === "react")
      return {
        ...React,
        useState(initial) {
          const at = cursor++;
          if (!(at in state)) state[at] = typeof initial === "function" ? initial() : initial;
          return [
            state[at],
            (v) => {
              state[at] = typeof v === "function" ? v(state[at]) : v;
            },
          ];
        },
        useRef(initial) {
          return (refs[cursor++] ||= { current: initial });
        },
        useEffect(fn, deps) {
          const at = cursor++,
            old = effects[at];
          if (!old || deps.some((v, i) => !Object.is(v, old.deps[i]))) {
            old?.cleanup?.();
            effects[at] = { deps, cleanup: fn() };
          }
        },
      };
    if (id === "react/jsx-runtime") return require(id);
    if (id === "react-router") return { useLocation: () => ({ pathname: "/chinese-demo/p/FLOW158/knowledge" }) };
    if (id === "./api")
      return {
        qualityApi: {
          write: async (...args) => {
            writes.push(args);
            return { id: "preview", valid: false, errors: [], rows: [], files: [], extraction: {} };
          },
          read: (url) => {
            const result = api(url);
            pending.push(Promise.resolve(result).catch(() => {}));
            return result;
          },
        },
        errorMessage: (e) => e.message,
      };
    return new Proxy({}, { get: (_, key) => (key === "fieldClass" ? "field" : stub(key)) });
  }, exp);
  const props = {
    resource: "knowledge",
    onClose() {},
    onSaved: async () => {},
    base: "/quality/",
    enabled: false,
    value: "",
    onChange: (v) => changed.push(v),
    onReadyChange: (v) => statuses.push(v),
  };
  return {
    changed,
    statuses,
    writes,
    props,
    render(extra = {}) {
      Object.assign(props, extra);
      cursor = 0;
      return file === "document-import-form" ? exp.DocumentImportForm(props) : exp.FeishuConnectionSelect(props);
    },
    async settle() {
      await Promise.all(pending);
      await Promise.resolve();
    },
    unmount() {
      effects.forEach((e) => e?.cleanup?.());
    },
  };
}
function nodes(t) {
  if (!t || typeof t !== "object") return [];
  if (Array.isArray(t)) return t.flatMap(nodes);
  return [t, ...nodes(t.props?.children)];
}
const text = (t) =>
  nodes(t)
    .flatMap((n) => [n.props?.children].flat())
    .filter((v) => typeof v === "string")
    .join("");
const select = (t) => nodes(t).find((n) => n.type === "select");
const button = (t, label) => nodes(t).find((n) => n.type === stub("Button") && n.props.children === label);
const page = (results, count = results.length, extra = {}) => ({
  results,
  count,
  page: 1,
  page_size: 20,
  can_configure: false,
  ...extra,
});

test("首次展开才读取已配置飞书连接，单个自动选择，不要求手填编号", async () => {
  const urls = [],
    h = harness(async (u) => {
      urls.push(u);
      return page([{ source_instance: "configured-one", label: "现场飞书" }]);
    });
  h.render();
  await h.settle();
  assert.equal(urls.length, 0);
  h.render({ enabled: true });
  await h.settle();
  const tree = h.render();
  assert.deepEqual(urls, ["/quality/document-imports/feishu/connections/?page=1&per_page=20&search="]);
  assert.deepEqual(h.changed, ["configured-one"]);
  assert.match(text(tree), /现场飞书/);
  assert.equal(
    nodes(tree).some((n) => n.type === "input" && n.props.name === "source_instance"),
    false
  );
});
test("多个连接不自动选，服务分页与搜索仍保留所选连接", async () => {
  const urls = [],
    h = harness(async (u) => {
      urls.push(u);
      return u.includes("?page=2&")
        ? page([{ source_instance: "other", label: "第二页" }], 21, { page: 2 })
        : page([{ source_instance: "first", label: "已选连接" }], 21);
    });
  let tree = h.render({ enabled: true });
  await h.settle();
  tree = h.render();
  assert.equal(h.changed.length, 0);
  select(tree).props.onChange({ target: { value: "first" } });
  assert.deepEqual(h.changed, ["first"]);
  h.render({ value: "first" });
  tree = h.render();
  button(tree, "下一页").props.onClick();
  h.render();
  await h.settle();
  tree = h.render();
  assert.ok(urls.some((u) => u.includes("?page=2&")));
  assert.equal(select(tree).props.value, "first");
  assert.match(text(tree), /已选连接/);
  nodes(tree)
    .find((n) => n.type === "input" && n.props.type === "search")
    .props.onChange({ target: { value: "名称 关键词" } });
  tree = h.render();
  button(tree, "搜索").props.onClick();
  h.render();
  await h.settle();
  tree = h.render();
  assert.match(urls.at(-1), /page=1&per_page=20&search=%E5%90%8D%E7%A7%B0%20%E5%85%B3%E9%94%AE%E8%AF%8D/);
  assert.equal(select(tree).props.value, "first");
  select(tree).props.onChange({ target: { value: "not-an-option" } });
  assert.deepEqual(h.changed, ["first"]);
});
test("空连接提示联系管理员，只给有配置权限者安全新标签入口", async () => {
  await Promise.all(
    [false, true].map(async (can_configure) => {
      const h = harness(async () => page([], 0, { can_configure }));
      h.render({ enabled: true });
      await h.settle();
      const tree = h.render();
      assert.match(text(tree), /尚未配置可用的飞书连接，请联系管理员。/);
      const link = nodes(tree).find((n) => n.type === "a");
      assert.equal(!!link, can_configure);
      if (link) {
        assert.equal(link.props.href, "/chinese-demo/settings/connections/?project=FLOW158");
        assert.equal(link.props.target, "_blank");
        assert.match(link.props.rel, /noopener/);
      }
    })
  );
});
test("网络失败清楚提示并可重试，关闭或切换base忽略旧结果", async () => {
  let calls = 0,
    resolve;
  const h = harness(() => {
    calls++;
    return calls === 1
      ? Promise.reject(new Error("连接列表读取失败"))
      : Promise.resolve(page([{ source_instance: "recovered", label: "已恢复" }]));
  });
  h.render({ enabled: true });
  await h.settle();
  let tree = h.render();
  assert.match(text(tree), /连接列表读取失败/);
  assert.equal(h.statuses.at(-1), false);
  button(tree, "重试").props.onClick();
  h.render();
  await h.settle();
  assert.deepEqual(h.changed, ["recovered"]);
  const pending = harness(
    () =>
      new Promise((done) => {
        resolve = done;
      })
  );
  pending.render({ enabled: true });
  pending.render({ enabled: false });
  resolve(page([{ source_instance: "late", label: "关闭后返回" }]));
  await pending.settle();
  assert.deepEqual(pending.changed, []);
});

test("切换项目后旧连接不沿用为新项目可读，未知响应及未配置连接不能就绪", async () => {
  const h = harness(async (u) =>
    u.startsWith("/other/") ? page([], 0) : page([{ source_instance: "old", label: "旧连接" }])
  );
  h.render({ enabled: true });
  await h.settle();
  h.render({ value: "old" });
  h.render({ base: "/other/" });
  await h.settle();
  h.render({ value: "" });
  assert.equal(h.changed.at(-1), "");
  assert.equal(h.statuses.at(-1), false);
  const invalid = harness(async () => page([{ source_instance: "user input secret", label: "无效" }], 1));
  invalid.render({ enabled: true });
  await invalid.settle();
  assert.deepEqual(invalid.changed, []);
  assert.equal(invalid.statuses.at(-1), false);
});

test("重新展开发现没有可用连接时清掉过期选择并禁止读取", async () => {
  let calls = 0;
  const h = harness(async () => (++calls === 1 ? page([{ source_instance: "old", label: "旧连接" }]) : page([], 0)));
  h.render({ enabled: true });
  await h.settle();
  h.render({ value: "old" });
  h.render({ enabled: false });
  h.render({ enabled: true });
  await h.settle();
  assert.equal(h.changed.at(-1), "");
  assert.equal(h.statuses.at(-1), false);
});

test("导入表单以列表选择和就绪状态控制读取，修改链接立即撤销旧预检", async () => {
  const h = harness(async () => page([]), "document-import-form");
  let tree = h.render();
  let child = nodes(tree).find((n) => n.type === stub("FeishuConnectionSelect"));
  assert.equal(child.props.enabled, false);
  nodes(tree)
    .find((n) => n.type === "details")
    .props.onToggle({ currentTarget: { open: true } });
  tree = h.render();
  child = nodes(tree).find((n) => n.type === stub("FeishuConnectionSelect"));
  assert.equal(child.props.enabled, true);
  child.props.onChange("chosen");
  child.props.onReadyChange(true);
  nodes(tree)
    .find((n) => n.type === "input" && n.props.placeholder === "https://company.feishu.cn/wiki/...")
    .props.onChange({ target: { value: "https://fixture.feishu.cn/docx/doc" } });
  tree = h.render();
  assert.equal(button(tree, "读取并预检").props.disabled, false);
  await button(tree, "读取并预检").props.onClick();
  assert.deepEqual(h.writes[0], [
    "/quality/document-imports/feishu/",
    { resource: "knowledge", source_instance: "chosen", url: "https://fixture.feishu.cn/docx/doc" },
  ]);
  tree = h.render();
  assert.match(text(tree), /预检未通过/);
  nodes(tree)
    .find((n) => n.type === "input" && n.props.placeholder === "https://company.feishu.cn/wiki/...")
    .props.onChange({ target: { value: "https://fixture.feishu.cn/docx/new" } });
  tree = h.render();
  assert.doesNotMatch(text(tree), /预检未通过/);
  nodes(tree)
    .find((n) => n.type === stub("FeishuConnectionSelect"))
    .props.onReadyChange(false);
  tree = h.render();
  assert.equal(button(tree, "读取并预检").props.disabled, true);
});
