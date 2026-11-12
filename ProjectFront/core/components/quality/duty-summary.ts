export function projectDutySummary(roles: string[]): { label: string; description: string } {
  const admin = roles.some((role) => ["管理员", "平台管理员", "实例管理员"].includes(role)),
    manager = roles.includes("项目经理");
  const remaining = admin ? [] : roles.filter((role) => role !== "项目经理" && role !== "数采员");
  const labels = [...(admin ? ["管理员"] : manager ? ["项目经理"] : []), ...remaining];
  const summaries: Record<string, string> = {
    技术员: "开发任务、修复缺陷",
    测试员: "执行测试、提交结果",
  };
  const descriptions = [
    ...(admin ? ["管理权限，处理全部岗位业务"] : manager ? ["排期分工、跟进验收"] : []),
    ...remaining.map((role) => summaries[role]).filter(Boolean),
  ];
  return { label: labels.join("、") || "项目成员", description: descriptions.join("；") || "反馈问题、补充材料" };
}

export function recordDutyLabels({
  userId,
  assigneeId,
  authorId,
  collaboratorIds = [],
  canArrange = false,
  kind = "记录",
}: {
  userId: string;
  assigneeId?: string | null;
  authorId?: string | null;
  collaboratorIds?: string[];
  canArrange?: boolean;
  kind?: string;
}): string[] {
  const labels = [
    ...(assigneeId === userId ? [kind === "测试计划" ? "测试执行人" : "负责人"] : []),
    ...(authorId === userId ? [kind === "缺陷" ? "上报人" : "创建人"] : []),
    ...(collaboratorIds.includes(userId) ? ["协作者"] : []),
    ...(canArrange ? ["项目统筹"] : []),
  ];
  return labels.length ? labels : ["查看记录"];
}

export function compactRecordDuty(labels: string[]): string {
  const priorities: [string, string][] = [
    ["负责人", "负责"],
    ["测试执行人", "执行"],
    ["协作者", "协作"],
    ["项目统筹", "统筹"],
    ["上报人", "上报"],
    ["创建人", "创建"],
  ];
  return priorities.find(([key]) => labels.includes(key))?.[1] || "";
}
