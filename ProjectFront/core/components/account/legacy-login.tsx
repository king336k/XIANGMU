// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { API_BASE_URL } from "@plane/constants";

async function requestJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { credentials: "include", ...options });
  if (!response.ok) {
    const error = (await response.json().catch(() => undefined)) as { detail?: string } | undefined;
    throw new Error(
      error?.detail ||
        (response.status === 429 ? "尝试次数过多，请稍后重试。" : "账号登录核验失败，请检查原账号及身份映射。")
    );
  }
  return response.json() as Promise<T>;
}

export function LegacyLoginForm() {
  const { data } = useSWR("quality-legacy-login-sources", () =>
    requestJson<{ sources: { source_instance: string }[] }>("/api/quality-auth/legacy-sources/")
  );
  const [open, setOpen] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  if (!data?.sources.length) return null;
  return (
    <section className="mx-auto mt-4 w-full max-w-[22.5rem] rounded-lg border border-subtle p-4">
      <button
        type="button"
        className="w-full text-left text-13 font-medium"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        使用原数据平台账号登录
      </button>
      {open && (
        <form
          className="mt-4 space-y-3"
          onSubmit={async (event) => {
            event.preventDefault();
            if (busy) return;
            const form = event.currentTarget;
            const values = new FormData(form);
            setBusy(true);
            setError("");
            try {
              const csrf = await requestJson<{ csrf_token: string }>("/auth/get-csrf-token/");
              const result = await requestJson<{ next: string }>("/api/quality-auth/legacy-login/", {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-CSRFToken": csrf.csrf_token },
                body: JSON.stringify({
                  source_instance: values.get("source_instance"),
                  username: values.get("username"),
                  password: values.get("password"),
                  ...(values.get("project_id") ? { project_id: values.get("project_id") } : {}),
                }),
              });
              form.reset();
              if (!result.next.startsWith("/") || result.next.startsWith("//"))
                throw new Error("登录成功，但跳转地址无效。请回到项目列表。");
              window.location.assign(result.next);
            } catch (cause) {
              setError(cause instanceof Error ? cause.message : "登录失败，请重试。");
            } finally {
              const input = form.elements.namedItem("password");
              if (input instanceof HTMLInputElement) input.value = "";
              setBusy(false);
            }
          }}
        >
          <p className="text-12 text-secondary">
            账号由原数据平台核验。首次使用前，请联系管理员完成身份映射；本平台按已确认的项目和角色授权，不保存原账号密码。
          </p>
          <label className="flex flex-col gap-1 text-12">
            账号来源
            <select name="source_instance" className="rounded border border-subtle bg-surface-1 p-2">
              {data.sources.map((source) => (
                <option key={source.source_instance} value={source.source_instance}>
                  {source.source_instance}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-12">
            原用户名
            <input
              required
              name="username"
              autoComplete="username"
              maxLength={64}
              className="rounded border border-subtle bg-surface-1 p-2"
            />
          </label>
          <label className="flex flex-col gap-1 text-12">
            原密码
            <input
              required
              type="password"
              name="password"
              autoComplete="current-password"
              maxLength={256}
              className="rounded border border-subtle bg-surface-1 p-2"
            />
          </label>
          <label className="flex flex-col gap-1 text-12">
            项目编号（可选）
            <input
              name="project_id"
              maxLength={36}
              className="rounded border border-subtle bg-surface-1 p-2"
              placeholder="多项目映射时由管理员提供"
            />
          </label>
          {error && (
            <p role="alert" className="text-12 text-danger-primary">
              {error}
            </p>
          )}
          <Button type="submit" disabled={busy}>
            {busy ? "正在核验…" : "登录平台"}
          </Button>
        </form>
      )}
    </section>
  );
}
