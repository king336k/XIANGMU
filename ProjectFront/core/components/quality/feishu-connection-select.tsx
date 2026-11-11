// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass } from "./shared";

type Connection = { source_instance: string; label: string };
type ConnectionPage = { results: Connection[]; count: number; can_configure: boolean; page: number; page_size: number };
export function FeishuConnectionSelect({
  base,
  enabled,
  value,
  onChange,
  onReadyChange,
}: {
  base: string;
  enabled: boolean;
  value: string;
  onChange: (value: string) => void;
  onReadyChange: (ready: boolean) => void;
}) {
  const location = useLocation();
  const [data, setData] = useState<ConnectionPage>(),
    [selected, setSelected] = useState<Connection>(),
    [input, setInput] = useState(""),
    [search, setSearch] = useState(""),
    [page, setPage] = useState(1),
    [busy, setBusy] = useState(false),
    [failure, setFailure] = useState(""),
    [retry, setRetry] = useState(0);
  const callbacks = useRef({ onChange, onReadyChange });
  callbacks.current = { onChange, onReadyChange };
  const chosenRef = useRef<Connection>();
  const valueRef = useRef(value);
  valueRef.current = value;
  const previousBase = useRef(base);
  useEffect(() => {
    if (previousBase.current !== base) {
      previousBase.current = base;
      chosenRef.current = undefined;
      valueRef.current = "";
      setData(undefined);
      setSelected(undefined);
      setPage(1);
      setSearch("");
      setInput("");
      callbacks.current.onChange("");
      callbacks.current.onReadyChange(false);
    }
  }, [base]);
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    setBusy(true);
    setFailure("");
    callbacks.current.onReadyChange(false);
    void qualityApi
      .read<ConnectionPage>(
        `${base}document-imports/feishu/connections/?page=${page}&per_page=20&search=${encodeURIComponent(search)}`
      )
      .then((result) => {
        if (!active) return null;
        if (
          !Array.isArray(result.results) ||
          !Number.isFinite(result.count) ||
          result.count < 0 ||
          result.results.length > 20 ||
          result.results.some(
            (item) => !/^[a-zA-Z0-9_-]{1,80}$/.test(item.source_instance) || typeof item.label !== "string"
          )
        )
          throw new Error("飞书连接列表无效，请重试。");
        setData(result);
        if (!search && result.count === 0) {
          chosenRef.current = undefined;
          setSelected(undefined);
          if (valueRef.current) callbacks.current.onChange("");
          callbacks.current.onReadyChange(false);
          return null;
        }
        const chosen =
          result.results.find((item) => item.source_instance === valueRef.current) ||
          (result.count === 1 && !search && !valueRef.current ? result.results[0] : undefined);
        if (chosen) {
          setSelected(chosen);
          chosenRef.current = chosen;
          if (chosen.source_instance !== valueRef.current) callbacks.current.onChange(chosen.source_instance);
          callbacks.current.onReadyChange(true);
        } else
          callbacks.current.onReadyChange(
            !!chosenRef.current && chosenRef.current.source_instance === valueRef.current
          );
        return null;
      })
      .catch((error: unknown) => {
        if (active) {
          setFailure(errorMessage(error));
          callbacks.current.onReadyChange(false);
        }
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [base, enabled, page, search, retry]);
  const prefix = location.pathname.match(/^\/([^/]+)\/p\/([^/]+)/);
  const apiProject = base.match(/^\/api\/workspaces\/([^/]+)\/projects\/([^/]+)\//);
  const configureHref = prefix
    ? `/${prefix[1]}/settings/connections/?project=${encodeURIComponent(apiProject?.[2] || prefix[2])}`
    : undefined;
  const options = data?.results || [];
  const visible =
    selected && !options.some((item) => item.source_instance === selected.source_instance)
      ? [selected, ...options]
      : options;
  return (
    <section className="space-y-3 text-12" aria-label="选择飞书连接">
      <p className="text-secondary">选择管理员配置好的连接，再粘贴飞书文档链接，无需填写 App ID 或凭据。</p>
      {busy && (
        <p role="status" className="text-secondary">
          正在读取飞书连接…
        </p>
      )}
      {failure && (
        <div role="alert" className="space-y-2 text-danger-primary">
          <p>{failure}</p>
          <Button type="button" variant="neutral-primary" onClick={() => setRetry((n) => n + 1)}>
            重试
          </Button>
        </div>
      )}
      {data && (
        <>
          {(data.count > 1 || search) && (
            <div className="flex flex-wrap gap-2">
              <Field label="搜索飞书连接">
                <input
                  type="search"
                  value={input}
                  maxLength={80}
                  className={fieldClass}
                  onChange={(event) => setInput(event.target.value)}
                />
              </Field>
              <Button
                type="button"
                variant="neutral-primary"
                disabled={busy}
                onClick={() => {
                  setPage(1);
                  setSearch(input.trim());
                }}
              >
                搜索
              </Button>
            </div>
          )}
          {visible.length > 0 && (
            <Field label="飞书连接">
              <select
                className={fieldClass}
                value={value}
                disabled={busy || !!failure}
                onChange={(event) => {
                  const chosen = visible.find((item) => item.source_instance === event.target.value);
                  if (!chosen) return;
                  setSelected(chosen);
                  chosenRef.current = chosen;
                  callbacks.current.onChange(chosen.source_instance);
                  callbacks.current.onReadyChange(true);
                }}
              >
                <option value="">请选择飞书连接</option>
                {visible.map((item) => (
                  <option key={item.source_instance} value={item.source_instance}>
                    {item.label}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {!data.count && (
            <p className="text-secondary">
              {search ? "没有找到匹配的飞书连接，请调整搜索条件。" : "尚未配置可用的飞书连接，请联系管理员。"}
            </p>
          )}
          {data.count > 20 && (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="neutral-primary"
                disabled={busy || page <= 1}
                onClick={() => setPage((n) => n - 1)}
              >
                上一页
              </Button>
              <span>
                第{page}页 · 共{data.count}个连接
              </span>
              <Button
                type="button"
                variant="neutral-primary"
                disabled={busy || page * 20 >= data.count}
                onClick={() => setPage((n) => n + 1)}
              >
                下一页
              </Button>
            </div>
          )}
          {data.can_configure && configureHref && (
            <a
              href={configureHref}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent-primary hover:underline"
            >
              配置飞书连接 ↗
            </a>
          )}
        </>
      )}
    </section>
  );
}
