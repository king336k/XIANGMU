import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url)),
  ts = require("typescript"),
  React = require("react");
test("同标题知识超过10条时，所选第11条也读取正文后才允许归并", async () => {
  const reads = [],
    effects = [];
  let cursor = 0;
  const state = [];
  const group = Array.from({ length: 11 }, (_, i) => ({ id: "k" + i, title: "同名", version: 1 }));
  const exports = {};
  const code = ts.transpileModule(
    readFileSync(new URL("../core/components/knowledge/governance-panel.tsx", import.meta.url), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }
  ).outputText;
  new Function("require", "exports", code)(
    (id) =>
      id === "react"
        ? {
            ...React,
            useState: (initial) => {
              const index = cursor++;
              if (!(index in state)) state[index] = initial;
              return [
                state[index],
                (value) => {
                  state[index] = value;
                },
              ];
            },
          }
        : id === "swr"
          ? {
              default: (key, fetcher) => {
                if (key?.includes("/compare/")) effects.push(fetcher());
                return {
                  data: !key
                    ? undefined
                    : key.includes("/compare/")
                      ? [{ id: "k10", content: "第11条" }]
                      : { total: 11, published: 0, review: 0, merged: 0, candidates: [group], scope: "" },
                  mutate() {},
                };
              },
            }
          : id === "../quality/api"
            ? {
                qualityApi: {
                  read: async (path) => {
                    reads.push(path);
                    return { id: path, content: "正文" };
                  },
                },
              }
            : id === "./semantic-index-panel"
              ? { SemanticIndexPanel: () => null }
              : id.startsWith("../quality")
                ? new Proxy({}, { get: () => () => null })
                : id === "@plane/ui"
                  ? { Button: () => null }
                  : require(id),
    exports
  );
  const render = () => {
    cursor = 0;
    return exports.GovernancePanel({ base: "/k/", isManager: true });
  };
  const nodes = (node) =>
    node && typeof node === "object" ? [node, ...React.Children.toArray(node.props?.children).flatMap(nodes)] : [];
  nodes(render())
    .find((node) => node.props?.children === "比较后归并")
    .props.onClick();
  nodes(render())
    .find((node) => node.type === "select" && node.props.name === "source_id")
    .props.onChange({ target: { value: "k10" } });
  nodes(render())
    .find((node) => node.type === "select" && node.props.name === "target_id")
    .props.onChange({ target: { value: "k0" } });
  reads.length = 0;
  effects.length = 0;
  render();
  await Promise.all(effects);
  assert.ok(reads.includes("/k/articles/k10/"));
  assert.ok(reads.length <= 2);
});
