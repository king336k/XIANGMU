from pathlib import Path
import re,json
manifest=Path('work/platform-copy-files.json');files=json.loads(manifest.read_text())
def edit(path,pairs):
 p=Path(path);s=p.read_text();o=s
 for a,b in pairs.items():s=s.replace(a,b)
 if s!=o:p.write_text(s);files.append(path)
base='ProjectFront/core/components/'
edit(base+'account/localization.test.mjs',{'if (name === "package.json")':'if (name === "next/link" || name === "@/layouts/default-layout") return { __esModule: true, default: widget };\n    if (name === "package.json")'})
for file,pairs in {
'onboarding/create-workspace.tsx':{'I want to join invited workspaces':'加入受邀工作空间'},
'onboarding/invite-members.tsx':{'Invite your teammates':'邀请成员','Work in plane happens best with your team. Invite them now to use Plane to its potential.':'填写成员邮箱并设置工作空间角色，也可以稍后邀请。'},
'onboarding/profile-setup.tsx':{'Set a password (':'设置密码（','placeholder="Wilbur"':'placeholder="请输入名字"','placeholder="Wright"':'placeholder="请输入姓氏"'},
'onboarding/step-indicator.tsx':{'{currentStep} of {totalSteps} steps':'第 {currentStep} 步，共 {totalSteps} 步'},
'onboarding/steps/profile/consent.tsx':{'I agree to Plane marketing communications':'同意接收 Plane 的产品营销邮件'},
}.items():edit(base+file,pairs)
# Shared password UI accepts an optional display-only label map; defaults and validation stay as before.
edit('packages/ui/src/form-fields/password/indicator.tsx',{'import { E_PASSWORD_STRENGTH }':'import { E_PASSWORD_STRENGTH }','  isFocused?: boolean;':'  isFocused?: boolean;\n  labels?: {\n    strength?: Partial<Record<E_PASSWORD_STRENGTH, string>>;\n    criteria?: Record<string, string>;\n  };','  isFocused = false,':'  isFocused = false,\n  labels,','{strengthInfo.message}':'{labels?.strength?.[strength] ?? strengthInfo.message}','{criterion.label}':'{labels?.criteria?.[criterion.key] ?? criterion.label}'})
p=Path(base+'account/password-labels.ts');p.write_text('''// SPDX-License-Identifier: AGPL-3.0-only
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
''');files.append(str(p))
for p in [*Path(base+'account').rglob('*.tsx'),*Path(base+'onboarding').rglob('*.tsx')]:
 s=p.read_text()
 if '<PasswordStrengthIndicator ' in s:
  s=s.replace('import { PasswordStrengthIndicator','import { PasswordStrengthIndicator')
  s=s.replace('// components\n','// components\nimport { passwordLabels } from "@/components/account/password-labels";\n',1) if '// components\n' in s else s.replace('import React,','import { passwordLabels } from "@/components/account/password-labels";\nimport React,',1)
  if 'import { passwordLabels }' not in s:s=s.replace('import { PasswordInput, PasswordStrengthIndicator } from "@plane/ui";','import { PasswordInput, PasswordStrengthIndicator } from "@plane/ui";\nimport { passwordLabels } from "@/components/account/password-labels";')
  if 'import { passwordLabels }' not in s:s='import { passwordLabels } from "@/components/account/password-labels";\n'+s
  s=s.replace('<PasswordStrengthIndicator ','<PasswordStrengthIndicator labels={passwordLabels} ');p.write_text(s);files.append(str(p))
# Web-only authentication banner messages. Error codes, mode switching, routes and payloads stay unchanged.
p=Path('ProjectFront/helpers/authentication.helper.tsx');s=p.read_text();o=s
pairs={
'Instance not configured':'平台实例尚未配置','Invalid email':'邮箱格式不正确','Email required':'请输入邮箱','Sign up disabled':'暂未开放注册','Magic link login disabled':'暂未启用邮件验证码登录','Password login disabled':'暂未启用密码登录','User account deactivated':'账号已停用','Sign in not allowed':'此账号无法登录','Invalid password':'密码不正确','Password too weak':'密码不符合要求','SMTP not configured':'邮件服务尚未配置','User already exists':'账号已存在','Email and password required':'请输入邮箱和密码','Authentication failed':'身份验证失败','Email and code required':'请输入邮箱和验证码','User does not exist':'未找到账号','Invalid magic code':'验证码不正确','Expired magic code':'验证码已失效','OAuth not configured':'OAuth 登录尚未配置','Google not configured':'Google 登录尚未配置','GitHub not configured':'GitHub 登录尚未配置','GitLab not configured':'GitLab 登录尚未配置','Google OAuth provider error':'Google 登录服务返回错误','GitHub OAuth provider error':'GitHub 登录服务返回错误','GitLab OAuth provider error':'GitLab 登录服务返回错误','Invalid password token':'密码重置链接无效','Expired password token':'密码重置链接已失效','Password required':'请输入密码','Incorrect old password':'原密码不正确','Invalid new password':'新密码不符合要求','Password already set':'密码已设置','Admin already exists':'管理员已存在','Email, password and first name required':'请输入邮箱、密码和姓名','Invalid admin email':'管理员邮箱格式不正确','Invalid admin password':'管理员密码不正确','Admin user already exists':'管理员账号已存在','Admin user does not exist':'未找到管理员账号','Admin user deactivated':'管理员账号已停用','Rate limit exceeded':'请求次数过多','Please contact your administrator.':'请联系管理员。','Please try again later.':'请稍后重试。','Please try again.':'请重试。','Please use a stronger password.':'请按密码要求补充字符。','This account cannot be used to sign in. Please use a personal account.':'此账号无法用于登录，请使用个人账号。','Your account is deactivated':'账号已停用','Your account is already registered.&nbsp;':'该邮箱已注册，请','No account found.&nbsp;':'未找到该邮箱对应的账号，可','Create one\n':'创建账号\n','Sign In\n':'登录\n','&nbsp;now.':'。','&nbsp;to get started.':'。','Admin user already exists.&nbsp;':'管理员账号已存在，请','Admin user does not exist.&nbsp;':'未找到管理员账号，请','"Error"':'"操作失败"','"Something went wrong. Please try again."':'"操作失败，请重试。"'}
# Replace complete textual sentences first so prefixes do not leave English fragments.
s=s.replace('message: () => `User account deactivated. Please contact ${SUPPORT_EMAIL ? SUPPORT_EMAIL : "administrator"}.`,','message: () => `账号已停用，请联系管理员。`,').replace('import { SUPPORT_EMAIL } from "@plane/constants";\n','')
for a,b in sorted(pairs.items(),key=lambda item:len(item[0]),reverse=True):s=s.replace(a,b)
s=re.sub(r'([\u4e00-\u9fff])\. ',r'\1。',s)
if s!=o:p.write_text(s);files.append(str(p))
manifest.write_text(json.dumps(sorted(set(files)),ensure_ascii=False,indent=2))
print('Total files',len(set(files)))
