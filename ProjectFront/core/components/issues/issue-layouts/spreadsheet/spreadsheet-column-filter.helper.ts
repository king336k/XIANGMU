import type { IWorkItemFilterInstance } from "@plane/shared-state";
import type {
  IIssueDisplayProperties,
  SingleOrArray,
  TFilterValue,
  TSupportedOperators,
  TWorkItemFilterProperty,
  TIssueOrderByOptions,
} from "@plane/types";
import { LOGICAL_OPERATOR } from "@plane/types";
import { removeNodeFromExpression, findNodeById, updateNodeInExpression } from "@plane/utils";

export const SPREADSHEET_COLUMN_FILTER_PROPERTIES: Partial<
  Record<keyof IIssueDisplayProperties, TWorkItemFilterProperty>
> = {
  state: "state_id",
  priority: "priority",
  assignee: "assignee_id",
  labels: "label_id",
  modules: "module_id",
  cycle: "cycle_id",
  start_date: "start_date",
  due_date: "target_date",
  created_on: "created_at",
  updated_on: "updated_at",
};

export const isSpreadsheetFilterExpressionEditable = (
  filter: IWorkItemFilterInstance | undefined,
  expression: unknown
) => !!filter && (!expression || Object.keys(expression).length === 0 || !!filter.expression);

export const getSpreadsheetColumnConditions = (filter: IWorkItemFilterInstance, property: TWorkItemFilterProperty) =>
  filter.allConditionsForDisplay.filter((condition) => condition.property === property);

// Use the shared instance's operations so advanced conditions, sort and pagination remain canonical.
export function updateSpreadsheetColumnFilter(
  filter: IWorkItemFilterInstance,
  property: TWorkItemFilterProperty,
  operator: TSupportedOperators,
  value: SingleOrArray<TFilterValue>,
  conditionId?: string
) {
  if (conditionId) {
    const current = filter.expression && findNodeById(filter.expression, conditionId);
    if (current?.type === "condition" && current.operator !== operator) {
      const expression = JSON.parse(JSON.stringify(filter.expression));
      updateNodeInExpression(expression, conditionId, { operator, value });
      filter.resetExpression(filter.adapter.toExternal(expression), false);
    } else filter.updateConditionValue(conditionId, value);
  } else filter.addCondition(LOGICAL_OPERATOR.AND, { property, operator, value }, false);
}

export function clearSpreadsheetColumnFilter(filter: IWorkItemFilterInstance, property: TWorkItemFilterProperty) {
  const conditions = getSpreadsheetColumnConditions(filter, property);
  if (conditions.length === 0) return;
  let expression = filter.expression;
  for (const condition of conditions) {
    if (expression) expression = removeNodeFromExpression(expression, condition.id).expression;
  }
  // Persist and refetch once, avoiding racing requests when a date column has several conditions.
  filter.resetExpression(filter.adapter.toExternal(expression), false);
}

export const getSpreadsheetSorts = (orderBy: string | undefined) =>
  (orderBy ?? "-created_at")
    .split(",")
    .map((field) => field.trim())
    .filter(Boolean);
export const getSpreadsheetSortField = (field: string) => field.replace(/^-/, "");

export function updateSpreadsheetColumnSort(orderBy: string | undefined, field: string, direction?: string) {
  const sorts =
    (orderBy === undefined || orderBy === "-created_at") && direction && getSpreadsheetSortField(field) !== "created_at"
      ? []
      : getSpreadsheetSorts(orderBy);
  const index = sorts.findIndex((sort) => getSpreadsheetSortField(sort) === getSpreadsheetSortField(field));
  if (index >= 0) {
    if (direction) sorts[index] = direction;
    else sorts.splice(index, 1);
  } else if (direction && sorts.length < 5) sorts.push(direction);
  return (sorts.join(",") || "-created_at") as TIssueOrderByOptions;
}

export function moveSpreadsheetColumnSort(orderBy: string | undefined, field: string, offset: -1 | 1) {
  const sorts = getSpreadsheetSorts(orderBy);
  const index = sorts.findIndex((sort) => getSpreadsheetSortField(sort) === getSpreadsheetSortField(field));
  const destination = index + offset;
  if (index >= 0 && destination >= 0 && destination < sorts.length) {
    [sorts[index], sorts[destination]] = [sorts[destination], sorts[index]];
  }
  return sorts.join(",") as TIssueOrderByOptions;
}
