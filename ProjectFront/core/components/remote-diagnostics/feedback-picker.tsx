// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useState } from "react";
import useSWR from "swr";
import { qualityApi, errorMessage } from "@/components/quality/api";
import { Modal, fieldClass } from "@/components/quality/shared";
import { remoteDiagnosticsBase } from "./types";
import type { RemoteDevice } from "./types";

export type FeedbackChoice = { id: string; code: string; title: string; latest_status?: string; run_count?: number };
const labels: Record<string, string> = {
  pending: "待处理",
  running: "处理中",
  repaired: "已修复",
  verified: "验证正常",
  unresolved: "需跟进",
};
export function FeedbackStatus({ value = "pending" }: { value?: string }) {
  return (
    <span
      className={`inline-flex shrink-0 rounded px-2 py-0.5 text-11 ${["repaired", "verified"].includes(value) ? "bg-success-subtle text-success-primary" : value === "running" ? "bg-accent-subtle text-accent-primary" : value === "unresolved" ? "bg-warning-subtle text-warning-primary" : "bg-surface-2 text-secondary"}`}
    >
      {labels[value] || "待确认"}
    </span>
  );
}

export function FeedbackPicker({
  device,
  value,
  onChange,
  optional = false,
  disabled = false,
}: {
  device: RemoteDevice;
  value?: FeedbackChoice;
  onChange: (value: FeedbackChoice | undefined) => void;
  optional?: boolean;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 rounded border border-subtle px-3 py-2 text-13">
        {value ? (
          <>
            <strong className="font-mono shrink-0 text-12">{value.code}</strong>
            <span className="min-w-0 flex-1 truncate" title={value.title}>
              {value.title}
            </span>
            <FeedbackStatus value={value.latest_status} />
          </>
        ) : (
          <span className="flex-1 text-secondary">{optional ? "不关联反馈" : "请选择原始反馈"}</span>
        )}
        <button
          type="button"
          disabled={disabled}
          onClick={() => setOpen(true)}
          className="shrink-0 text-12 text-accent-primary"
        >
          {value ? "更换" : "选择反馈"}
        </button>
        {value && (
          <a
            href={`/${device.workspace_slug}/p/${device.project_id}/defects/?defect=${value.id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0 text-12 text-accent-primary"
          >
            查看原反馈
          </a>
        )}
        {value && optional && (
          <button
            type="button"
            disabled={disabled}
            onClick={() => onChange(undefined)}
            className="text-12 text-secondary"
          >
            清空
          </button>
        )}
      </div>
      {open && (
        <FeedbackPickerDialog
          device={device}
          value={value}
          onClose={() => setOpen(false)}
          onConfirm={(next) => {
            onChange(next);
            setOpen(false);
          }}
        />
      )}
    </div>
  );
}

export function FeedbackPickerDialog({
  device,
  value,
  onClose,
  onConfirm,
}: {
  device: RemoteDevice;
  value?: FeedbackChoice;
  onClose: () => void;
  onConfirm: (value: FeedbackChoice) => void;
}) {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [state, setState] = useState("needs_attention");
  const [candidate, setCandidate] = useState(value);
  const [perPage, setPerPage] = useState(5);
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search);
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);
  const params = new URLSearchParams({
    device_id: device.id,
    q: query,
    state,
    page: String(page),
    per_page: String(perPage),
  });
  const { data, error } = useSWR(`${remoteDiagnosticsBase}feedback/?${params}`, (url: string) =>
    qualityApi.read<{ count: number; results: FeedbackChoice[] }>(url)
  );
  return (
    <Modal
      title="选择原始反馈"
      width="wide"
      onClose={onClose}
      submitLabel="确认选择"
      onSubmit={async () => {
        if (!candidate) throw new Error("请选择一条反馈。");
        onConfirm(candidate);
      }}
    >
      <p className="text-12 text-secondary">
        仅显示 {device.username}@{device.ip_address || "IP待确认"} 的反馈。
      </p>
      <div className="flex flex-wrap gap-2">
        <input
          aria-label="搜索当前电脑的反馈"
          placeholder="反馈编号或关键词"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className={`${fieldClass} min-w-48 flex-1`}
        />
        <select
          aria-label="反馈处理状态"
          value={state}
          onChange={(event) => {
            setState(event.target.value);
            setPage(1);
          }}
          className={`${fieldClass} w-auto`}
        >
          <option value="needs_attention">待处理与未解决</option>
          <option value="running">处理中</option>
          <option value="repaired">已修复并验证</option>
          <option value="all">全部反馈</option>
        </select>
      </div>
      {error ? (
        <p role="alert" className="text-13 text-danger-primary">
          {errorMessage(error)}
        </p>
      ) : !data ? (
        <p role="status" className="text-13 text-secondary">
          正在读取反馈…
        </p>
      ) : (
        <>
          <div className="overflow-auto rounded border border-subtle">
            <table className="w-full table-fixed text-left text-13">
              <thead className="bg-surface-2 text-12 text-secondary">
                <tr>
                  <th className="w-10 p-3">
                    <span className="sr-only">选择</span>
                  </th>
                  <th className="w-32 p-3">编号</th>
                  <th className="p-3">反馈内容</th>
                  <th className="w-32 p-3">状态</th>
                </tr>
              </thead>
              <tbody>
                {data.results.map((item) => (
                  <tr
                    key={item.id}
                    onClick={() => setCandidate(item)}
                    className={`cursor-pointer border-t border-subtle ${candidate?.id === item.id ? "bg-accent-subtle" : "hover:bg-surface-2"}`}
                  >
                    <td className="p-3">
                      <input
                        type="radio"
                        aria-label={`选择 ${item.code}`}
                        name="feedback-choice"
                        checked={candidate?.id === item.id}
                        onChange={() => setCandidate(item)}
                      />
                    </td>
                    <td className="font-mono p-3 text-12">{item.code}</td>
                    <td className="p-3">
                      <p className="truncate" title={item.title}>
                        {item.title}
                      </p>
                      {!!item.run_count && <span className="text-11 text-secondary">{item.run_count} 轮处理</span>}
                    </td>
                    <td className="p-3">
                      <FeedbackStatus value={item.latest_status} />
                    </td>
                  </tr>
                ))}
                {!data.results.length && (
                  <tr>
                    <td colSpan={4} className="p-6 text-center text-secondary">
                      没有匹配反馈，可调整关键词或状态。
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between text-12 text-secondary">
            <div className="flex items-center gap-3">
              <span>共 {data.count} 条</span>
              <select
                aria-label="每页反馈数量"
                value={perPage}
                onChange={(event) => {
                  setPerPage(Number(event.target.value));
                  setPage(1);
                }}
                className="rounded border border-subtle bg-surface-1 px-2 py-1"
              >
                <option value={5}>5 条 / 页</option>
                <option value={10}>10 条 / 页</option>
              </select>
            </div>
            <div className="flex items-center gap-3">
              <button type="button" disabled={page === 1} onClick={() => setPage(page - 1)}>
                上一页
              </button>
              <span>
                {page} / {Math.max(1, Math.ceil(data.count / perPage))}
              </span>
              <button type="button" disabled={page * perPage >= data.count} onClick={() => setPage(page + 1)}>
                下一页
              </button>
            </div>
          </div>
        </>
      )}
    </Modal>
  );
}
