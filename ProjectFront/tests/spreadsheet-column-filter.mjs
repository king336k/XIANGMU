import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(new URL("../package.json", import.meta.url));
const ts = require("typescript");
const React = require("react");
const Field = () => null;
const base = "../core/components/issues/issue-layouts/spreadsheet/";
const moduleCache = new Map();
function load(file, mocks = {}) {
  const sourceUrl = file instanceof URL ? file : new URL(base + file, import.meta.url);
  if (file instanceof URL && moduleCache.has(sourceUrl.href)) return moduleCache.get(sourceUrl.href);
  const exports = {};
  if (file instanceof URL) moduleCache.set(sourceUrl.href, exports);
  const code = ts.transpileModule(readFileSync(sourceUrl, "utf8"), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  new Function("require", "exports", code)((id) => {
    if (mocks[id]) return mocks[id];
    if (id.startsWith(".")) {
      const fileUrl = new URL(id + ".ts", sourceUrl);
      return load(existsSync(fileUrl) ? fileUrl : new URL(id + "/index.ts", sourceUrl), mocks);
    }
    return require(id);
  }, exports);
  return exports;
}
const types = {
  ...load(new URL("../../packages/types/src/view-props.ts", import.meta.url)),
  ...load(new URL("../../packages/types/src/rich-filters/operators/index.ts", import.meta.url)),
  ...load(new URL("../../packages/types/src/rich-filters/expression.ts", import.meta.url)),
  ...load(new URL("../../packages/types/src/rich-filters/field-types/index.ts", import.meta.url)),
};
const nativeConstants = {
  ...load(new URL("../../packages/constants/src/rich-filters/option.ts", import.meta.url)),
  ...load(new URL("../../packages/constants/src/rich-filters/operator-labels/index.ts", import.meta.url), {
    "@plane/types": types,
  }),
};
const nativeMocks = { "@plane/types": types, "@plane/constants": nativeConstants };
const nativeUtils = {
  ...load(new URL("../../packages/utils/src/rich-filters/types/index.ts", import.meta.url), nativeMocks),
  ...load(new URL("../../packages/utils/src/rich-filters/factories/nodes/core.ts", import.meta.url), nativeMocks),
  ...load(new URL("../../packages/utils/src/rich-filters/operations/index.ts", import.meta.url), nativeMocks),
  ...load(new URL("../../packages/utils/src/rich-filters/validators/index.ts", import.meta.url), nativeMocks),
  ...load(new URL("../../packages/utils/src/rich-filters/operators/index.ts", import.meta.url), nativeMocks),
};
const adapter = load(
  new URL("../../packages/shared-state/src/store/work-item-filters/adapter.ts", import.meta.url),
  { ...nativeMocks, "@plane/utils": nativeUtils }
).workItemFiltersAdapter;
const helper = () =>
  load("spreadsheet-column-filter.helper.ts", { "@plane/types": types, "@plane/utils": nativeUtils });
function nativeFilter(conditions = []) {
  const calls = [];
  return {
    calls,
    expression: conditions.length
      ? nativeUtils.createAndGroupNode(conditions.map((condition) => ({ type: "condition", ...condition })))
      : null,
    adapter,
    resetExpression(expression, resetInitial) {
      calls.push(["reset", expression, resetInitial]);
      this.expression = adapter.toInternal(expression);
      this.allConditionsForDisplay = this.allConditionsForDisplay.filter((condition) =>
        JSON.stringify(expression).includes(condition.property + "__")
      );
    },
    allConditionsForDisplay: conditions,
    addCondition(logical, condition, negative) {
      calls.push(["add", logical, condition, negative]);
      this.allConditionsForDisplay.push({ ...condition, id: `condition-${conditions.length}` });
    },
    updateConditionValue(id, value) {
      calls.push(["update", id, value]);
      this.allConditionsForDisplay.find((condition) => condition.id === id).value = value;
    },
    removeCondition(id) {
      calls.push(["remove", id]);
      this.allConditionsForDisplay = this.allConditionsForDisplay.filter((condition) => condition.id !== id);
    },
  };
}
test("同列多选通过原生 in 条件 OR，跨列通过原生 AND，序列化保留排序和高级条件", () => {
  const { updateSpreadsheetColumnFilter } = helper();
  const advanced = { id: "advanced", property: "created_at", operator: "range", value: ["2026-11-01", "2026-11-09"] };
  const filter = nativeFilter([advanced]);
  const displayFilters = { order_by: "state__name,-priority" };
  updateSpreadsheetColumnFilter(filter, "state_id", "in", ["state-a", "state-b"]);
  updateSpreadsheetColumnFilter(filter, "priority", "in", ["high", "urgent"]);
  assert.deepEqual(
    filter.calls.map((call) => [call[0], call[1], call[2].operator]),
    [
      ["add", "and", "in"],
      ["add", "and", "in"],
    ]
  );
  const payload = adapter.toExternal(
    nativeUtils.createAndGroupNode(
      filter.allConditionsForDisplay.map((condition) => ({ type: "condition", ...condition }))
    )
  );
  assert.deepEqual(JSON.parse(JSON.stringify(payload)), {
    and: [
      { created_at__range: "2026-11-01,2026-11-09" },
      { state_id__in: "state-a,state-b" },
      { priority__in: "high,urgent" },
    ],
  });
  assert.equal(displayFilters.order_by, "state__name,-priority");
  assert.equal(filter.allConditionsForDisplay[0], advanced);
});
test("修改和清空只触及选定条件；多重日期/高级运算符不被摊平或丢弃", () => {
  const { updateSpreadsheetColumnFilter, clearSpreadsheetColumnFilter, getSpreadsheetColumnConditions } = helper();
  const filter = nativeFilter([
    { id: "p", property: "priority", operator: "in", value: ["high"] },
    { id: "d1", property: "target_date", operator: "range", value: ["2026-11-01", "2026-11-20"] },
    { id: "d2", property: "target_date", operator: "exact", value: "2026-11-10" },
    { id: "s", property: "state_id", operator: "in", value: ["a"] },
  ]);
  updateSpreadsheetColumnFilter(filter, "priority", "in", ["urgent"], "p");
  assert.deepEqual(filter.calls, [["update", "p", ["urgent"]]]);
  assert.equal(getSpreadsheetColumnConditions(filter, "target_date").length, 2);
  clearSpreadsheetColumnFilter(filter, "target_date");
  assert.deepEqual(
    filter.allConditionsForDisplay.map((condition) => condition.id),
    ["p", "s"]
  );
});
test("多列排序追加、改变方向、移位和移除保留其他列顺序", () => {
  const { updateSpreadsheetColumnSort, moveSpreadsheetColumnSort } = helper();
  assert.equal(updateSpreadsheetColumnSort("-created_at", "state__name", "state__name"), "state__name");
  assert.equal(
    updateSpreadsheetColumnSort("state__name,-priority", "target_date", "-target_date"),
    "state__name,-priority,-target_date"
  );
  assert.equal(
    updateSpreadsheetColumnSort("state__name,-priority,-target_date", "priority", "priority"),
    "state__name,priority,-target_date"
  );
  assert.equal(
    updateSpreadsheetColumnSort("state__name,-priority,-target_date", "priority"),
    "state__name,-target_date"
  );
  assert.equal(
    moveSpreadsheetColumnSort("state__name,-priority,-target_date", "target_date", -1),
    "state__name,-target_date,-priority"
  );
  assert.equal(updateSpreadsheetColumnSort("priority", "priority"), "-created_at");
});
function nodes(tree) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
test("列筛选交互回调复用当前原生实例，支持中文标签和清空当前列", () => {
  const h = helper();
  const Popover = Object.assign(() => null, { Button: () => null, Panel: () => null });
  const filter = nativeFilter([{ id: "p", property: "priority", operator: "in", value: ["high"] }]);
  filter.configManager = {
    areConfigsReady: true,
    getConfigByProperty: () => ({
      isEnabled: true,
      firstOperator: "in",
      getOperatorConfig: () => ({ type: "multi_select", getOptions: [] }),
    }),
  };
  let cursor = 0;
  const state = [];
  const { SpreadsheetColumnFilter } = load("spreadsheet-column-filter.tsx", {
    react: {
      ...React,
      useState: (value) => {
        const index = cursor++;
        if (!(index in state)) state[index] = value;
        return [
          state[index],
          (value) => {
            state[index] = value;
          },
        ];
      },
    },
    "mobx-react": { observer: (fn) => fn },
    "lucide-react": { Filter: "filter-icon" },
    "@headlessui/react": { Popover },
    "react-popper": { usePopper: () => ({ styles: {}, attributes: {} }) },
    "@plane/types": types,
    "@plane/i18n": { useTranslation: () => ({ t: (key) => key }) },
    "@/components/rich-filters/filter-value-input/root": { FilterValueInput: Field },
    "@/components/rich-filters/filter-item/root": { FilterItem: () => null },
    "./spreadsheet-column-filter.helper": h,
    "./spreadsheet-option-checklist": { SpreadsheetOptionChecklist: Field },
  });
  const render = () => {
    cursor = 0;
    return SpreadsheetColumnFilter({ filter, property: "priority", label: "优先级" });
  };
  const tree = render();
  const all = nodes(tree);
  const field = all.find((node) => node.type === Field);
  assert.ok(field);
  field.props.onChange(["high", "urgent"]);
  assert.equal(filter.calls.length, 0, "勾选时不立即刷新关闭弹层，可继续多选");
  nodes(render())
    .find((node) => node.props?.children === "应用")
    .props.onClick();
  assert.deepEqual(filter.calls[0], ["update", "p", ["high", "urgent"]]);
  const clear = all.find((node) => node.type === "button" && node.props.children === "清除此列筛选");
  assert.ok(clear);
  clear.props.onClick();
  assert.deepEqual(filter.calls.at(-1), ["reset", {}, false]);
  assert.ok(all.some((node) => node.props?.["aria-label"] === "筛选优先级（1项）"));
});

test("真实原生 FilterInstance 回调与adapter序列化：组合筛选、单次清列、排序不变", () => {
  const { FilterInstance } = load(
    new URL("../../packages/shared-state/src/store/rich-filters/filter.ts", import.meta.url),
    { ...nativeMocks, "@plane/utils": nativeUtils }
  );
  const emitted = [];
  const filter = new FilterInstance({
    adapter,
    initialExpression: { and: [{ target_date__range: "2026-11-01,2026-11-20" }, { target_date__exact: "2026-11-10" }] },
    onExpressionChange: (expression) => emitted.push(expression),
  });
  const { updateSpreadsheetColumnFilter, clearSpreadsheetColumnFilter } = helper();
  updateSpreadsheetColumnFilter(filter, "state_id", "in", ["state-a", "state-b"]);
  updateSpreadsheetColumnFilter(filter, "priority", "in", ["high", "urgent"]);
  const before = emitted.length;
  clearSpreadsheetColumnFilter(filter, "target_date");
  assert.equal(emitted.length, before + 1, "多个日期条件必须只发出一次最终更新，防止请求竞态");
  assert.deepEqual(emitted.at(-1), { and: [{ state_id__in: "state-a,state-b" }, { priority__in: "high,urgent" }] });
  const serialized = JSON.parse(JSON.stringify({ filters: emitted.at(-1), order_by: "state__name,-priority" }));
  assert.equal(serialized.order_by, "state__name,-priority");
  assert.equal(serialized.filters.and.length, 2);
});

test("不支持的OR组合禁止列编辑，保留原始高级表达式", () => {
  const { isSpreadsheetFilterExpressionEditable } = helper();
  const raw = { or: [{ priority__in: "high" }, { state_id__in: "done" }] };
  const filter = { expression: null };
  assert.equal(isSpreadsheetFilterExpressionEditable(filter, raw), false);
  assert.deepEqual(raw, { or: [{ priority__in: "high" }, { state_id__in: "done" }] });
  assert.equal(isSpreadsheetFilterExpressionEditable(filter, {}), true);
  assert.equal(isSpreadsheetFilterExpressionEditable(undefined, {}), false);
});
const Menu = Object.assign(() => null, { MenuItem: () => null });
test("排序菜单操作仅更新order_by，徽标来自真实排序且最多5列", () => {
  const h = helper();
  const updates = [];
  const properties = {
    state: {
      i18n_title: "状态",
      ascendingOrderKey: "state__name",
      descendingOrderKey: "-state__name",
      ascendingOrderTitle: "A",
      descendingOrderTitle: "Z",
      icon: "state",
    },
    priority: {
      i18n_title: "优先级",
      ascendingOrderKey: "priority",
      descendingOrderKey: "-priority",
      ascendingOrderTitle: "None",
      descendingOrderTitle: "Urgent",
      icon: "priority",
    },
  };
  const { HeaderColumn } = load("columns/header-column.tsx", {
    "lucide-react": new Proxy({}, { get: (_, key) => key }),
    "@plane/constants": { SPREADSHEET_PROPERTY_DETAILS: properties },
    "@plane/i18n": { useTranslation: () => ({ t: (key) => key }) },
    "@plane/ui": { CustomMenu: Menu, Row: "row" },
    "../../utils": { SpreadSheetPropertyIcon: "property-icon" },
    "../spreadsheet-column-filter.helper": h,
  });
  const tree = HeaderColumn({
    property: "priority",
    displayFilters: { order_by: "state__name,-priority,target_date" },
    handleDisplayFilterUpdate: (value) => updates.push(value),
    onClose() {},
  });
  const choices = nodes(tree).filter((node) => node.type === Menu.MenuItem);
  choices[0].props.onClick();
  assert.deepEqual(updates.pop(), { order_by: "state__name,priority,target_date" });
  choices.find((node) => node.props.children === "提高排序优先级").props.onClick();
  assert.deepEqual(updates.pop(), { order_by: "-priority,state__name,target_date" });
  choices.at(-1).props.onClick();
  assert.deepEqual(updates.pop(), { order_by: "state__name,target_date" });
  assert.ok(nodes(tree.props.customButton).some((node) => node.props?.title === "第2排序条件"));
  const full = "state__name,-priority,target_date,start_date,updated_at";
  assert.equal(h.updateSpreadsheetColumnSort(full, "labels__name", "labels__name"), full);
});

test("旧单选条件恢复后改多选仍转换为IN，一次提交并保留其他列", () => {
  const filter = nativeFilter([
    { id: "old", property: "priority", operator: "exact", value: "high" },
    { id: "state", property: "state_id", operator: "in", value: ["done"] },
  ]);
  helper().updateSpreadsheetColumnFilter(filter, "priority", "in", ["high", "urgent"], "old");
  const serialized = JSON.stringify(filter.adapter.toExternal(filter.expression));
  assert.ok(serialized.includes("priority__in"));
  assert.ok(serialized.includes("state_id__in"));
  assert.equal(filter.calls.length, 1);
});
