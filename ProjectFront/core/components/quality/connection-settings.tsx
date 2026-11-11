// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass, Modal } from "./shared";
import { LegacyDirectoryPanel } from "./legacy-directory-panel";
import { connectionPayload } from "./connection-form-data";
import type { Connection } from "./connection-form-data";

export function ConnectionSettings({ base = "", endpoint }: { base?: string; endpoint?: string }) {
  const url = endpoint || `${base}integrations/connections/`;
  const { data, error, mutate } = useSWR(url, (path: string) =>
    qualityApi.read<{ can_configure: boolean; ota_directories_enabled?: boolean; results: Connection[] }>(path)
  );
  const [editing, setEditing] = useState<Connection | null | undefined>();
  const [preview, setPreview] = useState<string>();
  const [kind, setKind] = useState("data_platform");
  const [newSource, setNewSource] = useState("");
  const names: Record<string, string> = {
    data_platform: "数据平台",
    legacy_hub: "原45100账号服务",
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
              setKind("data_platform");
              setNewSource(`source-${crypto.randomUUID().replaceAll("-", "").slice(0, 16)}`);
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
            {row.kind === "legacy_hub" && base && (
              <Button variant="neutral-primary" onClick={() => setPreview(row.source_instance)}>
                账号迁移预检
              </Button>
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
              placeholder="例如 http://10.10.10.4:6324"
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
              {(kind === "data_platform" || kind === "legacy_hub") && (
                <>
                  <input type="hidden" name="login_options_present" value="1" />
                  <label className="flex gap-2 text-13">
                    <input type="checkbox" name="login_enabled" defaultChecked={editing?.login_enabled || false} />
                    允许来源账号登录
                  </label>
                  <label className="flex gap-2 text-13">
                    <input
                      type="checkbox"
                      name="login_auto_provision"
                      defaultChecked={editing?.login_auto_provision || false}
                    />
                    首次登录自动关联账号
                  </label>
                </>
              )}
              {kind === "data_platform" && (
                <details className="space-y-3">
                  <summary className="cursor-pointer text-13">DAQ 签名连接</summary>
                  <Field label="密钥编号">
                    <input
                      name="bridge_key_id"
                      defaultValue={editing?.bridge_key_id || ""}
                      className={fieldClass}
                      placeholder="自动生成"
                    />
                  </Field>
                  <Field label="接收方标识">
                    <input
                      name="bridge_audience"
                      defaultValue={editing?.bridge_audience || ""}
                      className={fieldClass}
                      placeholder="默认 plane-quality"
                    />
                  </Field>
                  <Field label="签名密钥（留空保留）">
                    <input
                      type="password"
                      name="bridge_secret"
                      autoComplete="new-password"
                      maxLength={4000}
                      className={fieldClass}
                      placeholder={editing?.bridge_secret_present ? "已配置" : "使用两端一致的签名密钥"}
                    />
                  </Field>
                </details>
              )}
              {kind === "legacy_hub" && (
                <details className="space-y-3">
                  <summary className="cursor-pointer text-13">原45100目录认证</summary>
                  <Field label="认证方式">
                    <select
                      name="directory_auth"
                      defaultValue={editing?.directory_auth || "bearer"}
                      className={fieldClass}
                    >
                      <option value="bearer">访问凭据</option>
                      <option value="trusted_v2">已有 V2 签名</option>
                    </select>
                  </Field>
                  <Field label="签名密钥编号">
                    <input
                      name="directory_key_id"
                      defaultValue={editing?.directory_key_id || ""}
                      maxLength={80}
                      className={fieldClass}
                    />
                  </Field>
                  <Field label="来源服务用户编号">
                    <input
                      name="directory_user_id"
                      type="number"
                      min={1}
                      defaultValue={editing?.directory_user_id || ""}
                      className={fieldClass}
                    />
                  </Field>
                  <Field label="来源服务用户名">
                    <input
                      name="directory_username"
                      defaultValue={editing?.directory_username || ""}
                      maxLength={64}
                      className={fieldClass}
                    />
                  </Field>
                </details>
              )}
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
      {preview && <LegacyDirectoryPanel base={base} instance={preview} onClose={() => setPreview(undefined)} />}
    </section>
  );
}
