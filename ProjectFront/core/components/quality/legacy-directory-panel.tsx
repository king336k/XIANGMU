// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Modal } from "./shared";
type Directory = {
  total: number;
  active: number;
  notice: string;
  results: {
    external_user_id: number;
    username: string;
    role_name: string;
    mapping_status: string;
    projects: { projectId: number; active: boolean; roles: string[] }[];
  }[];
};
export function LegacyDirectoryPanel({
  base,
  instance,
  onClose,
}: {
  base: string;
  instance: string;
  onClose: () => void;
}) {
  const [data, setData] = useState<Directory>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const check = async () => {
    setBusy(true);
    setError("");
    setData(undefined);
    try {
      setData(
        await qualityApi.read<Directory>(
          `${base}integrations/legacy-directory/?${new URLSearchParams({ source_instance: instance })}`
        )
      );
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title={`原账号迁移预检 · ${instance}`} onClose={onClose} width="wide">
      <p className="text-13 text-secondary">
        读取原45100账号目录，核对岗位、项目范围和当前项目的映射。此操作不创建账号、不导入密码、不自动授予权限。
      </p>
      <Button type="button" disabled={busy} onClick={() => void check()}>
        {busy ? "正在核对目录…" : data ? "重新读取目录" : "读取目录并预检"}
      </Button>
      {error && (
        <p role="alert" className="text-13 text-danger-primary">
          {error}
        </p>
      )}
      {data && (
        <>
          <p role="status" className="text-13">
            共 {data.total} 个原账号 · 有效 {data.active} 个 · 已停用 {data.total - data.active} 个
          </p>
          <div className="max-h-96 overflow-auto rounded-md border border-subtle">
            <table className="w-full text-left text-12">
              <thead className="sticky top-0 bg-layer-1">
                <tr>
                  <th className="p-3">原账号 / 编号</th>
                  <th className="p-3">原岗位</th>
                  <th className="p-3">有效项目编号</th>
                  <th className="p-3">当前项目映射</th>
                </tr>
              </thead>
              <tbody>
                {data.results.map((row) => (
                  <tr key={row.external_user_id} className="border-t border-subtle">
                    <td className="p-3">
                      <p>{row.username}</p>
                      <p className="mt-1 text-tertiary">原45100编号 {row.external_user_id}</p>
                    </td>
                    <td className="p-3">{row.role_name}</td>
                    <td className="p-3">
                      {row.projects
                        .filter((project) => project.active)
                        .map((project) => project.projectId)
                        .join("、") || "无有效项目"}
                    </td>
                    <td className="p-3">
                      {{ mapped: "已建立映射", disabled: "原账号已停用", unmapped: "待管理员映射" }[
                        row.mapping_status
                      ] || "需要核对"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-12 text-secondary">{data.notice}</p>
          <p className="text-12 text-secondary">
            原45100编号与数据平台用户编号不同；在“映射已有成员身份”中按对应来源实例和实际编号关联。标为“已建立映射”仍需核对项目角色、管理员授权和实际登录。
          </p>
        </>
      )}
    </Modal>
  );
}
