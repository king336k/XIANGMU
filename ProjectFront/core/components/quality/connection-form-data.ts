// SPDX-License-Identifier: AGPL-3.0-only
export type Connection = {
  source_instance: string;
  kind: string;
  base_url: string;
  timezone?: string;
  token_present?: boolean;
  bridge_secret_present?: boolean;
  login_enabled?: boolean;
  login_auto_provision?: boolean;
  portal_url?: string;
  roots?: string[];
  revision?: number;
  bridge_key_id?: string;
  bridge_audience?: string;
  directory_auth?: string;
  directory_key_id?: string;
  directory_user_id?: number | null;
  directory_username?: string;
};

export function connectionPayload(form: FormData, editing: Connection | null | undefined, directoriesEnabled: boolean) {
  const kind = String(form.get("kind") || editing?.kind || "data_platform");
  const payload: Record<string, unknown> = { kind, base_url: String(form.get("base_url") || "").trim() };
  const source = editing?.source_instance || String(form.get("source_instance") || "").trim();
  if (source) payload.source_instance = source;
  for (const key of ["service_token", "bridge_secret"]) {
    const value = form.get(key);
    if (typeof value === "string" && value.trim()) payload[key] = value;
  }
  for (const key of [
    "portal_url",
    "bridge_key_id",
    "bridge_audience",
    "directory_auth",
    "directory_key_id",
    "directory_username",
  ]) {
    if (form.has(key) && (editing || form.get(key))) payload[key] = form.get(key);
  }
  if (form.has("directory_user_id"))
    payload.directory_user_id = form.get("directory_user_id") ? Number(form.get("directory_user_id")) : null;
  if (form.has("login_options_present")) {
    payload.login_enabled = form.get("login_enabled") === "on";
    payload.login_auto_provision = form.get("login_auto_provision") === "on";
  }
  if (form.get("clear_token") === "on") payload.clear_token = true;
  if (kind === "ota" && directoriesEnabled) {
    payload.roots = String(form.get("roots") || "")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    payload.expected_revision = editing?.revision || 0;
  }
  return payload;
}
