import { v4 as uuidv4 } from "uuid";
// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass, Modal } from "./shared";
import { connectionPayload } from "./connection-form-data";
import type { Connection } from "./connection-form-data";

export function ConnectionSettings({ base = "", endpoint }: { base?: string; endpoint?: string }) {
  const url = endpoint || `${base}integrations/connections/`;
  const { data, error, mutate } = useSWR(url, (path: string) =>
    qualityApi.read<{ can_configure: boolean; ota_directories_enabled?: boolean; results: Connection[] }>(path)
  );
  const [editing, setEditing] = useState<Connection | null | undefined>();
  const [kind, setKind] = useState("feishu");
  const [newSource, setNewSource] = useState("");
  const names: Record<string, string> = {
    ota: data?.ota_directories_enabled ? "外部安装包目录" : "OTA/执行资源",
    feishu: "飞书服务",
  };
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-14 font-medium">已添加的连接</h3>
        {data?.can_configure && (
          <Button
            variant="neutral-primary"
            onClick={() => {
              setEditing(null);
              setKind("feishu");
              setNewSource(`source-${uuidv4().replaceAll("-", "").slice(0, 16)}`);
            }}
          >
            添加连接
          </Button>
        )}
      </div>
      {error && (
        <p role="alert" className="text-12 text-danger-primary">
          {errorMessage(error)}
        </p>
      )}
      {data?.results.map((row) => (
        <div
          key={row.source_instance}
          className="flex flex-wrap items-center justify-between gap-3 rounded border border-subtle p-3 text-12"
        >
          <div className="min-w-0">
            <p>
              {names[row.kind]} · {row.source_instance}
            </p>
            <p className="mt-1 break-all text-secondary">
              {row.base_url} · 凭据{row.token_present ? "已设置" : "未设置"}
            </p>
            {row.kind === "ota" && data?.ota_directories_enabled && (
              <ul aria-label="当前安装包目录" className="mt-2 space-y-1 text-12 text-secondary">
                {row.roots?.length ? (
                  row.roots.map((path) => (
                    <li key={path} className="break-all">
                      {path}
                    </li>
                  ))
                ) : (
                  <li>尚未填写安装包目录</li>
                )}
              </ul>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {row.kind === "ota" &&
              data?.ota_directories_enabled &&
              row.portal_url &&
              /^https?:\/\//.test(row.portal_url) && (
                <a
                  className="text-accent-primary hover:underline"
                  href={row.portal_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  打开外部部署平台 ↗
                </a>
              )}
            <Button
              variant="neutral-primary"
              onClick={() => {
                setEditing(row);
                setKind(row.kind);
              }}
            >
              编辑连接
            </Button>
          </div>
        </div>
      ))}
      {editing !== undefined && (
        <Modal
          title={editing ? "编辑连接" : "添加连接"}
          onClose={() => setEditing(undefined)}
          onSubmit={async (form) => {
            await qualityApi.write(url, connectionPayload(form, editing, data?.ota_directories_enabled === true));
            await mutate();
          }}
        >
          <Field label="平台类型">
            <select
              name="kind"
              value={kind}
              disabled={!!editing}
              onChange={(event) => setKind(event.target.value)}
              className={fieldClass}
            >
              {Object.entries(names).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
            {editing && <input type="hidden" name="kind" value={kind} />}
          </Field>
          <Field label="服务器地址 *">
            <input
              key={editing?.source_instance || kind}
              required
              name="base_url"
              type="url"
              defaultValue={editing?.base_url || (kind === "feishu" ? "https://open.feishu.cn" : "")}
              maxLength={500}
              className={fieldClass}
              placeholder="请输入服务地址"
            />
          </Field>
          <Field label={editing?.token_present ? "访问凭据（留空保留）" : "访问凭据"}>
            <input
              type="password"
              name="service_token"
              autoComplete="new-password"
              maxLength={4000}
              className={fieldClass}
              placeholder={editing?.token_present ? "已配置" : "由来源管理员提供"}
            />
          </Field>
          {kind === "ota" && data?.ota_directories_enabled && (
            <Field label="安装包目录（每行一个） *">
              <textarea
                required
                name="roots"
                rows={4}
                maxLength={10260}
                defaultValue={editing?.roots?.join("\n") || ""}
                className={fieldClass}
                placeholder="/srv/release-packages"
              />
            </Field>
          )}
          <details className="space-y-3 rounded border border-subtle p-3">
            <summary className="cursor-pointer text-13 font-medium">高级设置</summary>
            <div className="mt-3 space-y-3">
              <Field label="连接标识">
                <input
                  name="source_instance"
                  defaultValue={editing?.source_instance || newSource}
                  readOnly={!!editing}
                  pattern="[a-zA-Z0-9_-]{1,80}"
                  maxLength={80}
                  className={fieldClass}
                  placeholder="留空自动生成"
                />
              </Field>
              <Field label="浏览器访问地址">
                <input
                  name="portal_url"
                  type="url"
                  defaultValue={editing?.portal_url || ""}
                  className={fieldClass}
                  placeholder="留空使用服务器地址"
                />
              </Field>
              {editing?.token_present && (
                <label className="flex gap-2 text-13">
                  <input type="checkbox" name="clear_token" />
                  清除访问凭据
                </label>
              )}
            </div>
          </details>
        </Modal>
      )}
    </section>
  );
}
