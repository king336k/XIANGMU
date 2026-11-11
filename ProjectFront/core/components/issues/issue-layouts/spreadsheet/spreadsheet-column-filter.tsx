import { SpreadsheetOptionChecklist } from "./spreadsheet-option-checklist";
import { useState } from "react";
import { Popover } from "@headlessui/react";
import { Filter } from "lucide-react";
import { observer } from "mobx-react";
import { usePopper } from "react-popper";
import type { IWorkItemFilterInstance } from "@plane/shared-state";
import type { TWorkItemFilterProperty } from "@plane/types";
import { LOGICAL_OPERATOR } from "@plane/types";
import { FilterItem } from "@/components/rich-filters/filter-item/root";
import { FilterValueInput } from "@/components/rich-filters/filter-value-input/root";
import {
  clearSpreadsheetColumnFilter,
  getSpreadsheetColumnConditions,
  updateSpreadsheetColumnFilter,
} from "./spreadsheet-column-filter.helper";

type Props = { filter: IWorkItemFilterInstance; property: TWorkItemFilterProperty; label: string };

export const SpreadsheetColumnFilter = observer(function SpreadsheetColumnFilter({ filter, property, label }: Props) {
  const [draft, setDraft] = useState<string[] | undefined>();
  const [referenceElement, setReferenceElement] = useState<HTMLButtonElement | null>(null);
  const [popperElement, setPopperElement] = useState<HTMLDivElement | null>(null);
  const { styles, attributes } = usePopper(referenceElement, popperElement, {
    placement: "bottom-end",
    strategy: "fixed",
  });
  const config = filter.configManager.getConfigByProperty(property);
  const conditions = getSpreadsheetColumnConditions(filter, property);
  const count = conditions.reduce(
    (total, condition) =>
      total +
      (Array.isArray(condition.value)
        ? condition.value.length
        : condition.value == null || condition.value === ""
          ? 0
          : 1),
    0
  );
  const disabled = !filter.configManager.areConfigsReady || !config?.isEnabled;
  if (!config?.isEnabled && conditions.length === 0) return null;
  const operator = config?.firstOperator;
  // A simple column uses the exact native input. Multiple/advanced conditions keep their own operators and values.
  const simpleCondition =
    conditions.length === 1 &&
    (conditions[0].operator === operator || (operator === "in" && conditions[0].operator === "exact"))
      ? conditions[0]
      : undefined;
  const inputConfig = operator ? config?.getOperatorConfig(operator) : undefined;
  const canUseSimpleInput = !config?.allowMultipleFilters && (conditions.length === 0 || !!simpleCondition);
  return (
    <Popover className="flex shrink-0">
      <Popover.Button
        ref={setReferenceElement}
        type="button"
        disabled={disabled}
        onClick={() => setDraft(undefined)}
        aria-label={`筛选${label}${count ? `（${count}项）` : ""}`}
        title={`筛选${label}`}
        className={`flex items-center gap-0.5 rounded px-1 py-1 hover:bg-layer-2 ${count ? "text-accent-primary" : "text-tertiary"}`}
      >
        <Filter className="size-3.5" />
        {count > 0 && <span className="text-10">{count}</span>}
      </Popover.Button>
      <Popover.Panel
        ref={setPopperElement}
        style={styles.popper}
        {...attributes.popper}
        className="font-normal z-20 min-w-64 rounded border border-subtle bg-surface-1 p-3 text-left text-13 shadow-raised-100"
      >
        <div className="mb-2 font-medium">筛选{label}</div>
        {canUseSimpleInput && inputConfig && operator ? (
          "getOptions" in inputConfig ? (
            <SpreadsheetOptionChecklist
              config={inputConfig}
              property={property}
              value={draft ?? simpleCondition?.value}
              disabled={disabled}
              onChange={(value) => setDraft(value)}
            />
          ) : (
            <div className="flex min-h-8 rounded border border-subtle">
              <FilterValueInput
                condition={
                  simpleCondition ?? {
                    id: `spreadsheet-${property}`,
                    type: "condition",
                    property,
                    operator,
                    value: undefined,
                  }
                }
                filterFieldConfig={inputConfig}
                isDisabled={disabled}
                onChange={(value) =>
                  updateSpreadsheetColumnFilter(filter, property, operator, value, simpleCondition?.id)
                }
              />
            </div>
          )
        ) : (
          <div className="flex max-w-[36rem] flex-col items-start gap-2">
            {conditions.map((condition) => (
              <FilterItem key={condition.id} filter={filter} condition={condition} isDisabled={disabled} />
            ))}
          </div>
        )}
        {config?.allowMultipleFilters && operator && (
          <button
            type="button"
            className="mt-2 text-accent-primary"
            disabled={disabled}
            onClick={() => filter.addCondition(LOGICAL_OPERATOR.AND, { property, operator, value: undefined }, false)}
          >
            添加日期条件
          </button>
        )}
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-subtle pt-2">
          {canUseSimpleInput && inputConfig && "getOptions" in inputConfig && operator && (
            <Popover.Button
              type="button"
              className="rounded bg-accent-primary px-3 py-1.5 text-12 text-on-color"
              onClick={() => {
                if (draft) {
                  if (draft.length)
                    updateSpreadsheetColumnFilter(filter, property, operator, draft, simpleCondition?.id);
                  else clearSpreadsheetColumnFilter(filter, property);
                }
              }}
            >
              应用
            </Popover.Button>
          )}
          <button
            type="button"
            disabled={disabled || conditions.length === 0}
            className="text-accent-primary disabled:text-placeholder"
            onClick={() => clearSpreadsheetColumnFilter(filter, property)}
          >
            清除此列筛选
          </button>
          <button type="button" className="text-secondary" onClick={() => filter.toggleVisibility(true)}>
            查看全部筛选
          </button>
        </div>
      </Popover.Panel>
    </Popover>
  );
});
