// Run from the repository root: node ProjectFront/core/components/knowledge/assistant-state.test.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(new URL("../../../package.json", import.meta.url));
const ts = require("typescript");
const sourceUrl = new URL("./assistant-state.ts", import.meta.url);
const source = (() => {
  try {
    return readFileSync(sourceUrl, "utf8");
  } catch {
    return "";
  }
})();
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const mod = { exports: {} };
new Function("exports", "module", code)(mod.exports, mod);
const { prepareAttempt, mergeMessage, clearSentDraft, shouldSendOnEnter } = mod.exports;
assert.equal(typeof prepareAttempt, "function", "An uncertain retry must retain its original request ID");
let ids = 0;
const uuid = () => `request-${++ids}`;
const initial = prepareAttempt(undefined, "new", "  网络错误  ", uuid);
assert.equal(initial.query, "网络错误");
assert.equal(initial.conversation_id, undefined);
assert.equal(prepareAttempt(initial, "new", "网络错误", uuid), initial, "Same unanswered request reuses its ID");
assert.notEqual(prepareAttempt(initial, "conversation-2", "网络错误", uuid).request_id, initial.request_id);
assert.notEqual(prepareAttempt(initial, "new", "另一个问题", uuid).request_id, initial.request_id);
assert.equal(prepareAttempt(undefined, "conversation-2", "问题", uuid).conversation_id, "conversation-2");
const response = { id: "answer-1", conversation_id: "new-conversation", query: "问题" };
assert.deepEqual(mergeMessage(undefined, response), [response], "First reply seeds the returned conversation cache");
assert.deepEqual(mergeMessage([response], { ...response, answer: "更新" }), [{ ...response, answer: "更新" }]);
assert.equal(clearSentDraft("问题", "问题"), "");
assert.equal(clearSentDraft("问题\n新的草稿", "问题"), "问题\n新的草稿", "Response never clears a later draft");
assert.equal(shouldSendOnEnter({ key: "Enter", shiftKey: false, isComposing: false, keyCode: 13 }), true);
for (const event of [{ shiftKey: true }, { isComposing: true }, { keyCode: 229 }, { key: "a" }]) {
  assert.equal(shouldSendOnEnter({ key: "Enter", shiftKey: false, isComposing: false, keyCode: 13, ...event }), false);
}
console.log("Assistant request identity, conversation cache, retained drafts and IME regression checks passed.");
