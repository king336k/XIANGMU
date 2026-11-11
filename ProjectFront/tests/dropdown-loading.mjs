import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript"),
  React = require("react");
function load(source, mocks) {
  const exports = {};
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  new Function("require", "exports", code)(
    (id) =>
      mocks[id] || (id === "mobx-react" ? { observer: (fn) => fn } : id === "react/jsx-runtime" ? require(id) : {}),
    exports
  );
  return exports;
}
test("状态加载失败必须结束加载状态并保留重试/配置入口", async () => {
  const states = [];
  const source = readFileSync(new URL("../core/components/dropdowns/state/dropdown.tsx", import.meta.url), "utf8");
  const { StateDropdown } = load(source, {
    react: { ...React, useState: (value) => [value, (next) => states.push(next)] },
    "next/navigation": { useParams: () => ({ workspaceSlug: "workspace" }) },
    "@/hooks/store/use-project-state": {
      useProjectState: () => ({
        getProjectStateIds: () => [],
        getStateById: () => undefined,
        fetchProjectStates: async () => {
          throw new Error("offline");
        },
      }),
    },
    "./base": { WorkItemStateDropdownBase: () => null },
  });
  const tree = StateDropdown({ projectId: "project" });
  await tree.props.onDropdownOpen();
  assert.equal(states.at(-1), false);
  assert.ok(states.some((value) => typeof value === "string" && value.includes("状态加载失败")));
  assert.equal(tree.props.settingsUrl, "/workspace/settings/projects/project/states/");
});
test("周期初次展开必须请求服务端，空数组回退不能阻止加载", () => {
  const source = readFileSync(new URL("../core/components/dropdowns/cycle/cycle-options.tsx", import.meta.url), "utf8");
  const execute = (text) => {
    let fetched = 0;
    const effects = [];
    const { CycleOptions } = load(text, {
      react: {
        ...React,
        useState: (value) => [value, () => {}],
        useRef: () => ({ current: null }),
        useEffect: (fn) => effects.push(fn),
      },
      "next/navigation": { useParams: () => ({ workspaceSlug: "workspace" }) },
      "react-popper": { usePopper: () => ({ styles: {}, attributes: {} }) },
      "@headlessui/react": { Combobox: { Options: () => null, Input: () => null } },
      "@plane/propel/icons": new Proxy({}, { get: () => () => null }),
      "react-router": { Link: () => null },
      "@plane/i18n": { useTranslation: () => ({ t: (key) => key }) },
      "@/hooks/use-platform-os": { usePlatformOS: () => ({ isMobile: true }) },
      "@/hooks/store/use-cycle": {
        useCycle: () => ({
          getProjectCycleIds: () => undefined,
          getCycleById: () => undefined,
          fetchAllCycles: async () => {
            fetched++;
            return [];
          },
        }),
      },
    });
    CycleOptions({ projectId: "project", isOpen: true, referenceElement: null, canRemoveCycle: false });
    effects.forEach((fn) => fn());
    return fetched;
  };
  assert.equal(execute(source.replace("projectCycleIds === undefined", "!cycleIds")), 0);
  assert.equal(execute(source), 1);
});
