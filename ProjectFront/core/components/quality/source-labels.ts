const roles: Record<string, string> = {
  admin: "管理员",
  manager: "数据经理",
  teamleader: "组长",
  annotator: "标注员",
  collector: "数采员",
  pending: "待分配",
};
const states: Record<string, string> = {
  inprogress: "进行中",
  notstarted: "未开始",
  pending: "待处理",
  completed: "已完成",
  cancelled: "已取消",
  archived: "已归档",
  active: "有效",
  inactive: "已停用",
  deleted: "已删除",
  pendingannotation: "待标注",
  pendingreview: "待审核",
  pendingmanagerconfirmation: "待经理确认",
  reviewpassed: "审核通过",
  reviewfailed: "审核未通过",
  transferring: "上传中",
  transferfailed: "上传失败",
  convertfailed: "转换失败",
  recollectionrequired: "需重新采集",
};
const label = (names: Record<string, string>, value: string, fallback: string) =>
  names[value?.replace(/[_ -]/g, "").toLowerCase()] || (/\p{Script=Han}/u.test(value || "") ? value : fallback);
export const sourceRoleLabel = (value: string) => label(roles, value, "其他岗位");
export const sourceStatusLabel = (value: string) => label(states, value, "其他状态");
