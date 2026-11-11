// SPDX-License-Identifier: AGPL-3.0-only
export type DirectoryPerson = {
  id: string;
  username: string;
  display_name?: string;
  source?: string;
  is_administrator?: boolean;
};
export type AccessMembership = {
  id: string;
  role: number;
  original_role?: number;
  is_active?: boolean;
  is_administrator?: boolean;
  member: string | { id: string; username?: string; display_name?: string; first_name?: string; is_active?: boolean };
};
export const accessUserId = (row: AccessMembership) => (typeof row.member === "string" ? row.member : row.member.id);
const accessPerson = (row: AccessMembership) => (typeof row.member === "string" ? { id: row.member } : row.member);
export type MemberDuty = { user_id: string; roles: string[]; is_administrator?: boolean };
export type ManagedMember = DirectoryPerson & {
  roles: string[];
  projectMembership?: AccessMembership;
  workspaceMembership?: AccessMembership;
};
export function mergeMemberRows(
  project: AccessMembership[],
  workspace: AccessMembership[],
  duties: MemberDuty[],
  people: DirectoryPerson[],
  contextMembers: { id: string; name: string; business_roles?: string[]; is_administrator?: boolean }[],
  view: string
): ManagedMember[] {
  const result = new Map<string, ManagedMember>();
  const put = (id: string, data: Partial<ManagedMember>) =>
    result.set(id, { id, username: id, roles: [], ...result.get(id), ...data });
  if (view === "accounts") for (const p of people) put(p.id, p);
  if (view === "workspace")
    for (const p of workspace)
      put(accessUserId(p), {
        username: accessPerson(p).username || accessPerson(p).display_name || accessUserId(p),
        display_name: accessPerson(p).display_name,
        workspaceMembership: p,
        is_administrator: p.is_administrator === true,
      });
  for (const p of project)
    put(accessUserId(p), {
      username: accessPerson(p).username || accessPerson(p).display_name || accessUserId(p),
      display_name: accessPerson(p).display_name,
      projectMembership: p,
      is_administrator: p.is_administrator === true,
    });
  for (const p of contextMembers)
    if (result.has(p.id) || view !== "accounts")
      put(p.id, { display_name: p.name, roles: p.business_roles || [], is_administrator: p.is_administrator === true });
  for (const d of duties)
    if (result.has(d.user_id))
      put(d.user_id, {
        roles: d.roles.filter((r) => r !== "PLATFORM_ADMIN"),
        is_administrator: d.is_administrator === true,
      });
  for (const p of workspace) if (result.has(accessUserId(p))) put(accessUserId(p), { workspaceMembership: p });
  for (const p of people)
    if (result.has(p.id))
      put(p.id, {
        username: p.username,
        source: p.source,
        is_administrator: p.is_administrator === true || result.get(p.id)?.is_administrator === true,
      });
  return [...result.values()];
}
export async function joinMemberWithRoles({
  workspace,
  projectId,
  person,
  roles,
  progress,
  write,
}: {
  workspace: string;
  projectId: string;
  person: { user_id?: string; source_instance?: string; external_user_id?: number };
  roles: string[];
  progress: { userId?: string; personKey?: string; savedRoles?: string[] };
  write: <T>(url: string, data: object) => Promise<T>;
}) {
  if (!roles.length) throw Error("请至少选择一个业务岗位。");
  const personKey = JSON.stringify([
    workspace,
    projectId,
    person.user_id || null,
    person.source_instance || null,
    person.external_user_id || null,
  ]);
  if (progress.personKey !== personKey) {
    progress.userId = undefined;
    progress.savedRoles = undefined;
    progress.personKey = personKey;
  }
  if (!progress.userId) {
    const joined = await write<{ user_id: string }>(
      `/api/quality-auth/accounts/${workspace}/projects/${projectId}/members/`,
      { ...person, role: roles[0] }
    );
    if (!joined.user_id) throw Error("加入结果缺少人员编号，请刷新成员列表核对后重试。");
    progress.userId = joined.user_id;
    progress.savedRoles = [roles[0]];
  }
  if (JSON.stringify(progress.savedRoles) !== JSON.stringify(roles))
    try {
      await write(`/api/workspaces/${workspace}/projects/${projectId}/quality/roles/`, {
        user_id: progress.userId,
        roles,
      });
      progress.savedRoles = [...roles];
    } catch {
      throw Error("已加入项目并保存首次岗位；其余岗位未保存，请重试。不会重复创建或加入账号。");
    }
}
export const DUTY_LABELS: Record<string, string> = {
  PROJECT_MANAGER: "项目经理",
  TECHNICIAN: "技术员",
  REGRESSION_TESTER: "测试员",
  REPORTER: "数采员",
};
export const ACCESS_LABELS: Record<number, string> = { 5: "只读访问", 15: "可参与项目", 20: "访问管理" };

export function memberAccessLabel(person: ManagedMember, projectScope: boolean): string {
  const account = [person.projectMembership, person.workspaceMembership].find(
    (row) => row && accessPerson(row).is_active === false
  );
  if (account) return "账号已停用";
  if (person.workspaceMembership?.is_active === false) return "已移出工作空间";
  const membership = projectScope ? person.projectMembership : person.workspaceMembership;
  if (membership?.is_active === false) return projectScope ? "已移出项目" : "已移出工作空间";
  return membership ? ACCESS_LABELS[membership.role] || "成员" : projectScope ? "未加入本项目" : "未加入工作空间";
}
