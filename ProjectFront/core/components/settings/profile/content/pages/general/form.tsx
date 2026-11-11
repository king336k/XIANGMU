import { projectDutySummary } from "@/components/quality/duty-summary";
/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import useSWR from "swr";
import { qualityApi, errorMessage } from "@/components/quality/api";
import { observer } from "mobx-react";
import { CircleUserRound } from "lucide-react";
// plane imports
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { IUser, TUserProfile } from "@plane/types";
import { getFileURL } from "@plane/utils";
import { Avatar } from "@plane/ui";
// components
import { UserImageUploadModal } from "@/components/core/modals/user-image-upload-modal";
// helpers
// hooks
// utils

import { useUser } from "@/hooks/store/user";

type TAccountProfile = {
  username: string;
  source_label: string;
  email: string;
  portal_url: string;
  can_edit_identity: boolean;
  project_duties: { project_id: string; identifier: string; url: string; project: string; roles: string[] }[];
  platform_role?: string;
};

const sourceRoles: Record<string, string> = {
  Admin: "管理员",
  Manager: "数据经理",
  TeamLeader: "组长",
  Annotator: "标注员",
  Auditor: "审核员",
  Collector: "数采员",
  Pending: "待分配用户",
};

type Props = {
  user: IUser;
  profile: TUserProfile;
};

export const GeneralProfileSettingsForm = observer(function GeneralProfileSettingsForm(_props: Props) {
  const { data: account, error: accountError } = useSWR("/api/quality-auth/account-security/", (url: string) =>
    qualityApi.read<TAccountProfile>(url)
  );
  // states
  const [isLoading, setIsLoading] = useState(false);
  const [isImageUploadModalOpen, setIsImageUploadModalOpen] = useState(false);
  const { data: currentUser, updateCurrentUser } = useUser();
  const userAvatar = currentUser?.avatar_url || "";
  const saveAvatar = async (url: string) => {
    setIsLoading(true);
    try {
      await updateCurrentUser({ avatar_url: url });
      setIsImageUploadModalOpen(false);
      setToast({ type: TOAST_TYPE.SUCCESS, title: "已更新头像" });
    } catch {
      throw new Error("头像更新失败，请重试");
    } finally {
      setIsLoading(false);
    }
  };
  return (
    <>
      <UserImageUploadModal
        isOpen={isImageUploadModalOpen}
        onClose={() => setIsImageUploadModalOpen(false)}
        handleRemove={() => saveAvatar("")}
        onSuccess={saveAvatar}
        value={userAvatar || null}
      />
      <div className="w-full min-w-0 space-y-7">
        <button
          type="button"
          disabled={isLoading}
          onClick={() => setIsImageUploadModalOpen(true)}
          className="flex items-center gap-3 rounded-md text-13 text-secondary hover:text-primary"
          aria-label="修改头像"
        >
          <span className="flex size-12 items-center justify-center overflow-hidden rounded-md bg-layer-1">
            {userAvatar ? (
              <Avatar src={getFileURL(userAvatar)} name={account?.username || "账号"} size={48} shape="square" />
            ) : (
              <CircleUserRound className="size-8" />
            )}
          </span>
          修改头像
        </button>
        <section className="mt-6 space-y-4" aria-label="账号资料">
          {accountError ? (
            <p role="alert" className="text-13 text-danger-primary">
              {errorMessage(accountError)}
            </p>
          ) : !account ? (
            <p role="status" className="text-13 text-secondary">
              正在读取账号资料…
            </p>
          ) : (
            <>
              <dl className="grid grid-cols-1 gap-5 sm:grid-cols-2">
                <div>
                  <dt className="text-12 text-secondary">用户名</dt>
                  <dd className="mt-1 text-14 font-medium break-all">{account.username}</dd>
                </div>
                <div>
                  <dt className="text-12 text-secondary">账号来源</dt>
                  <dd className="mt-1 text-13">{account.source_label}</dd>
                </div>
                {account.email && (
                  <div>
                    <dt className="text-12 text-secondary">邮箱</dt>
                    <dd className="mt-1 text-13 break-all">{account.email}</dd>
                  </div>
                )}
                {account.platform_role && (
                  <div>
                    <dt className="text-12 text-secondary">数据平台角色</dt>
                    <dd className="mt-1 text-13">{sourceRoles[account.platform_role] || account.platform_role}</dd>
                  </div>
                )}
              </dl>
              <section className="border-t border-subtle pt-5" aria-label="我参与的项目">
                <h3 className="mb-3 text-14 font-medium">
                  我参与的项目{" "}
                  <span className="font-normal ml-1 text-12 text-secondary">{account.project_duties.length}</span>
                </h3>
                {account.project_duties.length ? (
                  <div className="max-h-80 overflow-auto rounded-md border border-subtle">
                    <table className="w-full text-left text-13">
                      <thead className="sticky top-0 bg-surface-1 text-12 text-secondary">
                        <tr>
                          <th className="px-4 py-2.5 font-medium">项目</th>
                          <th className="px-4 py-2.5 font-medium">我的职责</th>
                        </tr>
                      </thead>
                      <tbody>
                        {account.project_duties.map((duty) => (
                          <tr key={duty.project_id || duty.project} className="border-t border-subtle hover:bg-layer-1">
                            <td className="px-4 py-3">
                              <a href={duty.url} className="platform-record-link inline-flex flex-col gap-1">
                                <span>{duty.project}</span>
                              </a>
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex flex-col gap-1 text-13 text-primary">
                                <span>{projectDutySummary(duty.roles).label}</span>
                                {projectDutySummary(duty.roles).description && (
                                  <span className="text-12 leading-5 text-secondary">
                                    {projectDutySummary(duty.roles).description}
                                  </span>
                                )}
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="text-13 text-secondary">尚未加入项目。</p>
                )}
              </section>
              {!account.can_edit_identity && account.portal_url && (
                <a
                  href={account.portal_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex text-12 text-accent-primary hover:underline"
                >
                  在数据管理平台管理账号
                </a>
              )}
            </>
          )}
        </section>
      </div>
    </>
  );
});
