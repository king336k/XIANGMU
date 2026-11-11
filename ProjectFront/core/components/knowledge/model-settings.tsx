// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "../quality/api";
import { Field, fieldClass } from "../quality/shared";

type Configuration = {
  configured: boolean;
  key_present: boolean;
  model: string;
  base_url: string;
  can_configure: boolean;
  scope: string;
  semantic_enabled?: boolean;
  embedding_model?: string;
  embedding_base_url?: string;
  embedding_key_present?: boolean;
  semantic?: {
    source?: "builtin" | "external" | "shared";
    managed?: boolean;
    configured?: boolean;
    enabled?: boolean;
    status?: string;
  };
};
export function ModelSettings({ base, endpoint }: { base: string; endpoint?: string }) {
  const url = endpoint || `${base}configuration/`;
  const { data, error, mutate } = useSWR(url, (path: string) => qualityApi.read<Configuration>(path));
  const [busy, setBusy] = useState(false),
    [message, setMessage] = useState(""),
    [advancedOpen, setAdvancedOpen] = useState(false),
    [embeddingMode, setEmbeddingMode] = useState("");
  const searchName =
    data?.semantic?.source === "external"
      ? "外部知识检索"
      : data?.semantic?.source === "builtin" || data?.semantic?.managed
        ? "内置知识检索"
        : "知识检索";
  return (
    <section className="max-w-2xl space-y-5">
      {!endpoint && <h2 className="text-18 font-semibold">模型配置</h2>}
      <p className="text-13">
        当前状态：{data?.configured ? "已配置" : "尚未配置"} · 密钥：
        {data?.key_present ? "已设置" : "未设置"}
      </p>
      {error && (
        <p role="alert" className="text-13 text-danger-primary">
          {errorMessage(error)}
        </p>
      )}
      {data && (
        <form
          key={`${data.model}:${data.base_url}:${data.key_present}:${data.semantic_enabled}:${data.embedding_model}:${data.embedding_base_url}`}
          className="space-y-4"
          onSubmit={async (event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            const useExternal = advancedOpen && embeddingMode === "external";
            if (
              useExternal &&
              (!String(form.get("embedding_model") || "").trim() ||
                !String(form.get("embedding_base_url") || "").trim())
            ) {
              setMessage("请填写外部向量模型和独立接口地址。");
              return;
            }
            setBusy(true);
            setMessage("");
            try {
              await qualityApi.write(
                url,
                {
                  model: form.get("model"),
                  base_url: form.get("base_url"),
                  api_key: form.get("api_key") || "",
                  clear_key: form.get("clear_key") === "on",
                  ...(useExternal
                    ? {
                        embedding_mode: "external",
                        semantic_enabled: true,
                        embedding_model: form.get("embedding_model"),
                        embedding_base_url: form.get("embedding_base_url"),
                        embedding_api_key: form.get("embedding_api_key") || "",
                        clear_embedding_key: form.get("clear_embedding_key") === "on",
                      }
                    : advancedOpen && embeddingMode === "builtin"
                      ? { embedding_mode: "builtin", semantic_enabled: true }
                      : {}),
                },
                "patch"
              );
              await mutate();
              setEmbeddingMode("");
              setMessage("已保存。");
            } catch (e) {
              setMessage(errorMessage(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          <Field label="模型名称 *">
            <input
              required
              name="model"
              maxLength={120}
              defaultValue={data.model}
              disabled={!data.can_configure}
              className={fieldClass}
            />
          </Field>
          <Field label="模型接口地址 *">
            <input
              required
              name="base_url"
              type="url"
              maxLength={500}
              defaultValue={data.base_url}
              disabled={!data.can_configure}
              className={fieldClass}
            />
          </Field>
          {data.can_configure ? (
            <>
              <Field label="API密钥（留空保留）">
                <input
                  type="password"
                  name="api_key"
                  autoComplete="new-password"
                  maxLength={4000}
                  className={fieldClass}
                />
              </Field>
              {data.key_present && (
                <label className="flex items-center gap-2 text-12">
                  <input type="checkbox" name="clear_key" />
                  清除已保存的密钥，停用模型问答
                </label>
              )}
              <p className="text-12 text-secondary">接口主机须在服务器允许列表中。</p>
              <details
                className="space-y-3 border-t border-subtle pt-4"
                onToggle={(event) => {
                  setAdvancedOpen(event.currentTarget.open);
                  if (!event.currentTarget.open) setEmbeddingMode("");
                }}
              >
                <summary className="cursor-pointer text-13">高级设置：外部向量服务</summary>
                <Field label="检索服务设置">
                  <select
                    name="embedding_mode"
                    value={embeddingMode}
                    onChange={(event) => setEmbeddingMode(event.target.value)}
                    className={fieldClass}
                  >
                    <option value="">保留当前检索服务</option>
                    <option value="builtin">恢复平台内置服务</option>
                    <option value="external">使用外部向量服务</option>
                  </select>
                </Field>
                {advancedOpen && embeddingMode === "external" && (
                  <fieldset className="space-y-3">
                    <legend className="text-14 font-medium">外部向量连接</legend>
                    <Field label="向量模型名称 *">
                      <input
                        required
                        name="embedding_model"
                        maxLength={120}
                        defaultValue={data.semantic?.source === "external" ? data.embedding_model || "" : ""}
                        className={fieldClass}
                        placeholder="填写当前接口支持的向量模型名称"
                      />
                    </Field>
                    <p className="text-12 text-secondary">密钥留空保留原值。</p>
                    <Field label="向量接口地址 *">
                      <input
                        required
                        name="embedding_base_url"
                        type="url"
                        maxLength={500}
                        defaultValue={data.semantic?.source === "external" ? data.embedding_base_url || "" : ""}
                        className={fieldClass}
                        placeholder="https://embedding.example.com/v1"
                      />
                    </Field>
                    <Field label="向量服务密钥（留空保留）">
                      <input
                        type="password"
                        name="embedding_api_key"
                        maxLength={4000}
                        autoComplete="new-password"
                        className={fieldClass}
                      />
                    </Field>
                    {data.embedding_key_present && (
                      <label className="flex items-center gap-2 text-12">
                        <input type="checkbox" name="clear_embedding_key" />
                        清除向量服务密钥
                      </label>
                    )}
                  </fieldset>
                )}
              </details>
              <Button type="submit" disabled={busy}>
                {busy ? "正在保存…" : "保存模型配置"}
              </Button>
            </>
          ) : (
            <p className="text-13 text-secondary">修改模型配置请联系管理员。</p>
          )}
        </form>
      )}
      {data && (
        <div className="space-y-1 rounded-md border border-subtle p-3 text-12 text-secondary">
          <p>默认诊断引擎：PydanticAI · 使用上方对话模型。</p>
          <p role="status">
            {searchName} ·{" "}
            {data.semantic?.source === "shared" || (!data.semantic?.source && !data.semantic?.managed)
              ? "待接通"
              : data.semantic?.configured && data.semantic.status === "ready"
                ? "已就绪"
                : "未就绪"}
          </p>
          {data.embedding_model && <p>检索模型：{data.embedding_model}</p>}
          <p>
            {data.semantic?.source === "external"
              ? "当前使用外部向量服务。"
              : data.semantic?.source === "shared" || (!data.semantic?.source && !data.semantic?.managed)
                ? "尚未配置检索服务。"
                : "平台部署管理，无需重复设置。"}
          </p>
        </div>
      )}
      {message && (
        <p role="status" className="text-13">
          {message}
        </p>
      )}
    </section>
  );
}
