// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { Eye, EyeOff } from "lucide-react";
import { API_BASE_URL } from "@plane/constants";
import { Button } from "@plane/ui";
import { authErrorHandler, EAuthenticationErrorCodes } from "@/helpers/authentication.helper";

async function readJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { credentials: "include", ...options });
  if (!response.ok) {
    const data = (await response.json().catch(() => undefined)) as { detail?: string } | undefined;
    throw new Error(
      data?.detail || (response.status === 429 ? "尝试次数过多，请稍后重试。" : "登录失败，请检查账号和密码。")
    );
  }
  return response.json() as Promise<T>;
}

export function UsernameLoginForm() {
  const params = useSearchParams();
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const errorCode = params.get("error_code");
  const banner = error || (errorCode ? authErrorHandler(errorCode as EAuthenticationErrorCodes)?.message : undefined);
  return (
    <form
      className="space-y-5"
      method="POST"
      action={`${API_BASE_URL}/api/quality-auth/login/`}
      aria-label="账号密码登录"
      onSubmit={async (event) => {
        event.preventDefault();
        if (busy) return;
        const form = event.currentTarget;
        setBusy(true);
        setError("");
        try {
          const csrf = await readJson<{ csrf_token: string }>("/auth/get-csrf-token/");
          if (!csrf.csrf_token) throw new Error("登录校验未就绪，请刷新后重试。");
          const values = new FormData(form);
          const result = await readJson<{ next: string }>("/api/quality-auth/login/", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-CSRFToken": csrf.csrf_token },
            body: JSON.stringify({
              username: String(values.get("username") || "").trim(),
              password: values.get("password"),
              next_path: params.get("next_path") || "",
            }),
          });
          form.reset();
          if (!result.next.startsWith("/") || result.next.startsWith("//"))
            throw new Error("登录跳转地址无效，请联系管理员。");
          window.location.assign(result.next);
        } catch (cause) {
          setError(cause instanceof Error ? cause.message : "登录失败，请稍后重试。");
          const password = form.elements.namedItem("password");
          if (password instanceof HTMLInputElement) password.value = "";
          setBusy(false);
        }
      }}
    >
      <input type="hidden" name="csrfmiddlewaretoken" />
      {params.get("next_path") && <input type="hidden" name="next_path" value={params.get("next_path")!} />}
      <label className="grid grid-cols-[3.5rem_minmax(0,1fr)] items-center gap-3 text-13 text-secondary">
        用户名
        <input
          name="username"
          type="text"
          aria-label="用户名"
          required
          maxLength={128}
          autoComplete="username"
          readOnly={busy}
          placeholder="请输入用户名"
          className="h-10 w-full rounded-md border border-[#cbdad3] bg-surface-1 px-3 text-primary outline-none focus:border-[#16826c] focus:ring-2 focus:ring-[#16826c]/15 dark:border-[#3d554a]"
        />
      </label>
      <label className="grid grid-cols-[3.5rem_minmax(0,1fr)] items-center gap-3 text-13 text-secondary">
        密码
        <span className="relative">
          <input
            name="password"
            type={showPassword ? "text" : "password"}
            aria-label="密码"
            required
            maxLength={256}
            autoComplete="current-password"
            readOnly={busy}
            placeholder="请输入密码"
            className="h-10 w-full rounded-md border border-[#cbdad3] bg-surface-1 pr-10 pl-3 text-primary outline-none focus:border-[#16826c] focus:ring-2 focus:ring-[#16826c]/15 dark:border-[#3d554a]"
          />
          <button
            type="button"
            aria-label={showPassword ? "隐藏密码" : "显示密码"}
            onClick={() => setShowPassword(!showPassword)}
            className="absolute top-2 right-2 rounded p-1 text-secondary"
          >
            {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          </button>
        </span>
      </label>
      {banner && (
        <p role="alert" className="rounded-md bg-danger-subtle p-3 text-12 text-danger-primary">
          {banner}
        </p>
      )}
      <Button
        type="submit"
        disabled={busy}
        className="h-10 w-full !border-[#16826c] !bg-[#16826c] text-14 !text-white hover:!bg-[#116955] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#16826c]"
      >
        {busy ? "正在登录…" : "登录"}
      </Button>
    </form>
  );
}
