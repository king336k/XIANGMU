import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
test("状态列打开直接列出复选项，搜索过滤中文选项，勾选保留同列原选择", async () => {
  let cursor = 0,
    changed;
  const values = [],
    effects = [],
    api = {};
  const code = ts.transpileModule(
    readFileSync(
      new URL("../core/components/issues/issue-layouts/spreadsheet/spreadsheet-option-checklist.tsx", import.meta.url),
      "utf8"
    ),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
  ).outputText;
  new Function("require", "exports", code)(
    (id) =>
      id === "react"
        ? {
            ...React,
            useState: (initial) => {
              const index = cursor++;
              if (!(index in values)) values[index] = initial;
              return [
                values[index],
                (value) => {
                  values[index] = value;
                },
              ];
            },
            useEffect: (fn) => effects.push(fn),
          }
        : id === "@plane/i18n"
          ? { useTranslation: () => ({ t: (value) => value }) }
          : require(id),
    api
  );
  const props = {
    config: {
      getOptions: [
        { value: "open", label: "待处理" },
        { value: "done", label: "已完成" },
      ],
    },
    property: "state_id",
    value: ["open"],
    disabled: false,
    onChange: (value) => {
      changed = value;
    },
  };
  const render = () => {
    cursor = 0;
    return api.SpreadsheetOptionChecklist(props);
  };
  render();
  effects[0]();
  for (let step = 0; step < 5; step++) await Promise.resolve();
  const tree = render(),
    labels = tree.props.children[1].props.children;
  assert.equal(labels.length, 2);
  assert.equal(labels[0].props.children[0].props.checked, true);
  labels[1].props.children[0].props.onChange({ target: { checked: true } });
  assert.deepEqual(changed, ["open", "done"]);
  tree.props.children[0].props.onChange({ target: { value: "已完成" } });
  assert.equal(render().props.children[1].props.children.length, 1);
});
