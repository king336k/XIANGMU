export type NativeWorkRules = Record<
  string,
  { can_arrange: boolean; can_edit: boolean; own_only: boolean; can_edit_documents?: boolean }
>;
export function nativeWorkAllowed(
  rules: NativeWorkRules | undefined,
  projectId: string | undefined,
  mode: "arrange" | "edit",
  userId?: string,
  assigneeIds?: string[]
): boolean {
  const row = projectId ? rules?.[projectId] : undefined;
  if (!row) return false;
  if (mode === "arrange") return row.can_arrange;
  return row.can_edit && (!row.own_only || Boolean(userId && assigneeIds?.includes(userId)));
}
