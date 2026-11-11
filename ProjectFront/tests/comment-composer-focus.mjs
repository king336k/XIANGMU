import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
function setup() {
  const api = {},
    slots = [];
  let cursor = 0;
  const source = readFileSync(new URL("../core/components/editor/lite-text/editor.tsx", import.meta.url), "utf8");
  new Function(
    "require",
    "exports",
    ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
    }).outputText
  )((id) => {
    if (id === "react")
      return {
        ...React,
        default: { ...React, forwardRef: (fn) => (props) => fn(props, props.ref) },
        useState: (initial) => {
          const index = cursor++;
          if (!(index in slots)) slots[index] = initial;
          return [
            slots[index],
            (v) => {
              slots[index] = v;
            },
          ];
        },
      };
    if (id === "mobx-react") return { observer: (fn) => fn };
    if (id === "react/jsx-runtime") return require(id);
    if (id === "@plane/utils")
      return {
        cn: (...args) => args.filter((x) => typeof x === "string").join(" "),
        isCommentEmpty: (value) => !value || value === "<p></p>",
      };
    if (id === "@plane/i18n") return { useTranslation: () => ({ t: (key) => key }) };
    if (id.includes("use-editor-flagging"))
      return { useEditorFlagging: () => ({ liteText: { disabled: [], flagged: [] } }) };
    if (id.includes("use-member")) return { useMember: () => ({ getUserDetails() {} }) };
    if (id.includes("use-parse-editor")) return { useParseEditorContent: () => ({ getEditorMetaData() {} }) };
    if (id.includes("use-editor-mention")) return { useEditorMention: () => ({ fetchMentions() {} }) };
    if (id === "@/hooks/editor")
      return {
        useEditorConfig: () => ({ getEditorFileHandlers() {} }),
        useEditorMention: () => ({ fetchMentions() {} }),
      };
    if (id === "@/services/workspace.service") return { WorkspaceService: function () {} };
    return new Proxy({}, { get: () => () => null });
  }, api);
  return {
    render(initialValue = "<p></p>") {
      cursor = 0;
      return api.LiteTextEditor({
        ref: { current: null },
        editable: true,
        workspaceSlug: "w",
        workspaceId: "w",
        projectId: "p",
        id: "comment",
        initialValue,
        showToolbarInitially: false,
      });
    },
  };
}
function toolbar(tree) {
  return tree.props.children.at(-1);
}
test("空评论默认收起工具栏，聚焦后展开，点击外部恢复紧凑", () => {
  const x = setup();
  let tree = x.render();
  assert.match(toolbar(tree).props.className, /invisible/);
  tree.props.onFocus();
  tree = x.render();
  assert.doesNotMatch(toolbar(tree).props.className, /invisible/);
  tree.props.onBlur({ currentTarget: { contains: () => false }, relatedTarget: null });
  tree = x.render();
  assert.match(toolbar(tree).props.className, /invisible/);
});
test("切换工具栏内部焦点不收起，有文字或图片的草稿在失焦后仍可提交", () => {
  const x = setup();
  let tree = x.render();
  tree.props.onFocus();
  tree = x.render();
  tree.props.onBlur({ currentTarget: { contains: () => true }, relatedTarget: {} });
  tree = x.render();
  assert.doesNotMatch(toolbar(tree).props.className, /invisible/);
  tree.props.onBlur({ currentTarget: { contains: () => false }, relatedTarget: null });
  for (const value of ["<p>尚未发布的评论</p>", '<image-component id="upload"></image-component>'])
    assert.doesNotMatch(toolbar(x.render(value)).props.className, /invisible/);
});
