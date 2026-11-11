// Translate built-in filter metadata by stable keys; never translate user-defined names.
export const FILTER_PROPERTY_TRANSLATIONS: Record<string, string> = {
  state_group: "common.state_groups",
  state_id: "common.state",
  label_id: "common.labels",
  cycle_id: "common.cycle",
  module_id: "common.module",
  assignee_id: "common.assignees",
  mention_id: "mentions",
  created_by_id: "common.created_by",
  subscriber_id: "filters_workspace.subscribers",
  priority: "common.priority",
  project_id: "common.projects",
  start_date: "start_date",
  target_date: "target_date",
  created_at: "common.sort.created_on",
  updated_at: "common.sort.updated_on",
};

export const FILTER_OPERATOR_TRANSLATIONS: Record<string, string> = {
  exact: "filters_workspace.operators.exact",
  in: "filters_workspace.operators.in",
  range: "filters_workspace.operators.range",
};
