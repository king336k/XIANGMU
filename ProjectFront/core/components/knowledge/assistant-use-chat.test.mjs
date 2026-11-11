// Run from the repository root: node ProjectFront/core/components/knowledge/assistant-use-chat.test.mjs
// This in-process fixture exercises the real hook without contacting a model or server.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../../../package.json", import.meta.url));
const ts = require("typescript");
function compile(name, resolver) {
  const code = ts.transpileModule(readFileSync(new URL(name, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const mod = { exports: {} };
  new Function("require", "exports", "module", code)(resolver, mod.exports, mod);
  return mod.exports;
}
const helpers = compile("./assistant-state.ts", require);
function fixture() {
  let cursor = 0;
  const slots = [];
  const cache = new Map([
    ["/knowledge/status/", { configured: false }],
    ["/knowledge/conversations/all", []],
  ]);
  const requests = [];
  let respond;
  let reject;
  const mutate = async (key, update) => {
    if (typeof update === "function") cache.set(key, update(cache.get(key)));
    return cache.get(key);
  };
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = initial;
      return [
        slots[index],
        (value) => {
          slots[index] = typeof value === "function" ? value(slots[index]) : value;
        },
      ];
    },
    useRef(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = { current: initial };
      return slots[index];
    },
  };
  const swr = Object.assign((key) => ({ data: cache.get(key), mutate: () => mutate(key), isLoading: false }), {
    useSWRConfig: () => ({ mutate }),
  });
  const api = {
    qualityApi: {
      write: async (_url, payload) => {
        requests.push(payload);
        return await new Promise((resolve, failure) => {
          respond = resolve;
          reject = failure;
        });
      },
    },
    errorMessage: () => "调用失败",
  };
  const { useAssistantChat } = compile("./assistant-use-chat.ts", (name) => {
    if (name === "react") return react;
    if (name === "swr") return { default: swr, useSWRConfig: swr.useSWRConfig };
    if (name === "axios") return { isAxiosError: (error) => error?.isAxiosError === true };
    if (name === "./assistant-state") return helpers;
    if (name === "@/components/quality/api") return api;
    throw new Error(`Unexpected fixture dependency: ${name}`);
  });
  return {
    cache,
    requests,
    render: (allowed = true) => {
      cursor = 0;
      return useAssistantChat("/knowledge/", allowed);
    },
    respond: (value) => respond(value),
    reject: (value) => reject(value),
  };
}
const response = {
  id: "answer-1",
  conversation_id: "saved-chat",
  query: "检查网络",
  answer: "本地测试夹具",
  created_at: "2026-11-07T00:00:00Z",
};
{
  const f = fixture();
  f.render().setDraft("检查网络");
  await f.render().send();
  assert.equal(f.requests.length, 0, "Unconfigured model never receives a request");
  f.cache.set("/knowledge/status/", { configured: true });
  await f.render(false).send();
  assert.equal(f.requests.length, 0, "Permission check applies inside send");
  const completion = f.render().send();
  assert.equal(f.requests.length, 1);
  await f.render().send();
  assert.equal(f.requests.length, 1, "A second submit is blocked synchronously");
  f.respond(response);
  await completion;
  assert.equal(f.render().selected, "saved-chat");
  assert.equal(f.render().draft, "");
  assert.deepEqual(
    f.cache.get("/knowledge/conversations/saved-chat/all"),
    [response],
    "First response appears on the new conversation key"
  );
  assert.equal(f.cache.get("/knowledge/conversations/all")[0].id, "saved-chat");
}
{
  const f = fixture();
  f.cache.set("/knowledge/status/", { configured: true });
  f.render().select("old-chat");
  f.render().setDraft("检查网络");
  const completion = f.render().send();
  f.render().select("another-chat");
  f.render().setDraft("下一条草稿");
  f.respond({ ...response, conversation_id: "old-chat" });
  await completion;
  assert.equal(f.render().selected, "another-chat", "A background reply never steals the selected conversation");
  assert.equal(f.render().draft, "下一条草稿");
  f.render().select("old-chat");
  assert.equal(f.render().draft, "");
  assert.equal(f.cache.get("/knowledge/conversations/old-chat/all")[0].id, "answer-1");
}
{
  const f = fixture();
  f.cache.set("/knowledge/status/", { configured: true });
  f.render().setDraft("检查网络");
  const first = f.render().send();
  f.reject(new Error("network interrupted"));
  await first;
  assert.equal(f.render().draft, "检查网络");
  const second = f.render().send();
  assert.equal(f.requests[1].request_id, f.requests[0].request_id, "Uncertain retry is idempotent");
  f.reject({ isAxiosError: true, response: { status: 502, data: { code: "AI_PROVIDER_UNAVAILABLE" } } });
  await second;
  const third = f.render().send();
  assert.notEqual(
    f.requests[2].request_id,
    f.requests[1].request_id,
    "Confirmed terminal failure permits a fresh attempt"
  );
  f.respond(response);
  await third;
}
{
  const f = fixture();
  f.cache.set("/knowledge/status/", { configured: true });
  f.render().setDraft("检查网络");
  const completion = f.render().send();
  f.render().setDraft("下一条未发送内容");
  f.respond(response);
  await completion;
  assert.equal(f.render().selected, "saved-chat");
  assert.equal(f.render().draft, "下一条未发送内容", "Typing during first reply follows the newly saved conversation");
}
console.log(
  "Assistant hook fixture passed: disabled sends, duplicate submit, first reply, background ownership, drafts and safe retries."
);
