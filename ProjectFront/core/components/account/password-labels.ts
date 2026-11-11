// SPDX-License-Identifier: AGPL-3.0-only
import { E_PASSWORD_STRENGTH } from "@plane/constants";

export const passwordLabels = {
  strength: {
    [E_PASSWORD_STRENGTH.EMPTY]: "请输入密码",
    [E_PASSWORD_STRENGTH.LENGTH_NOT_VALID]: "密码至少需要 8 个字符",
    [E_PASSWORD_STRENGTH.STRENGTH_NOT_VALID]: "请按下方要求补充字符",
    [E_PASSWORD_STRENGTH.STRENGTH_VALID]: "密码符合要求",
  },
  criteria: {
    length: "至少 8 个字符",
    uppercase: "至少 1 个大写字母",
    lowercase: "至少 1 个小写字母",
    number: "至少 1 个数字",
    special: "至少 1 个特殊字符",
  },
};
