import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
function harness(fail) {
  const api = {},
    resets = [],
    submitted = [],
    order = [];
  const mocks = {
    react: { ...React, useEffect() {}, useState: () => [true, () => {}] },
    "mobx-react": { observer: (fn) => fn },
    "next/navigation": { useParams: () => ({ workspaceSlug: "w", projectId: "p" }) },
    "react-hook-form": {
      useForm: () => ({
        reset: (value) => {
          resets.push(value);
          order.push("reset");
        },
        handleSubmit: (fn) => () => fn({ name: "保留重试标题" }),
        register() {},
        formState: { errors: {}, isSubmitting: false },
      }),
    },
    "@plane/i18n": { useTranslation: () => ({ t: (key) => key }) },
    "@plane/utils": { cn: () => "", createIssuePayload: (_id, data) => data },
    "@plane/propel/toast": { setPromiseToast: () => {} },
  };
  new Function(
    "require",
    "exports",
    ts.transpileModule(
      readFileSync(new URL("../core/components/issues/issue-layouts/quick-add/root.tsx", import.meta.url), "utf8"),
      { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
    ).outputText
  )((id) => mocks[id] || (id === "react/jsx-runtime" ? require(id) : new Proxy({}, { get: () => () => null })), api);
  const tree = api.QuickAddIssueRoot({
    layout: "kanban",
    isQuickAddOpen: true,
    quickAddCallback: async (_project, data) => {
      submitted.push(data);
      order.push("request");
      if (fail) throw Error("offline");
      order.push("saved");
      return { id: "created" };
    },
  });
  return { resets, submitted, order, submit: tree.props.children.props.onSubmit };
}
test("快速新建网络失败保留标题，允许原内容重试", async () => {
  const h = harness(true);
  await assert.rejects(h.submit(), /offline/);
  assert.deepEqual(h.submitted, [{ name: "保留重试标题" }]);
  assert.equal(h.resets.length, 0);
});
test("快速新建保存成功后才清空输入", async () => {
  const h = harness(false);
  await h.submit();
  assert.deepEqual(h.order, ["request", "saved", "reset"]);
  assert.deepEqual(h.resets, [{ name: "" }]);
});
