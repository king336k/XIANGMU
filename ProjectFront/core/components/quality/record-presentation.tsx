// SPDX-License-Identifier: AGPL-3.0-only
import type { ReactNode } from "react";
import { Badge } from "./record-badge";
import { ChevronDown } from "lucide-react";
import { TableHeaderFilter } from "./table-header-filter";
import type { Context } from "./types";
import type { RecordLayout } from "./layout-controls";
type Row = {
  id: string;
  code?: string;
  title: string;
  subtitle?: string;
  status: string;
  statusName: string;
  severity?: string;
  values: string[];
};
export function RecordPresentation({
  rows,
  layout,
  columns,
  onOpen,
  kind,
  context,
  selectedIds,
  onToggle,
  onTogglePage,
  onStatusChange,
  canChangeStatus,
  onFieldChange,
  canChangeField,
  renderActions,
}: {
  renderActions?: (id: string) => ReactNode;
  rows: Row[];
  layout: RecordLayout;
  columns: string[];
  onOpen: (id: string) => void;
  kind?: string;
  context?: Context;
  selectedIds?: string[];
  onToggle?: (id: string, checked: boolean) => void;
  onTogglePage?: (checked: boolean) => void;
  onStatusChange?: (id: string) => void;
  canChangeStatus?: (id: string) => boolean;
  onFieldChange?: (id: string, field: "severity" | "assignee") => void;
  canChangeField?: (id: string, field: "severity" | "assignee") => boolean;
}) {
  const statusLabel = (row: Row) =>
    (kind === "defects" || kind === "requirements") && onStatusChange && canChangeStatus?.(row.id) ? (
      <button
        type="button"
        aria-label={`${kind === "requirements" ? "更新需求状态" : "更新处理状态"}：${row.title}`}
        title={kind === "requirements" ? "更新需求状态" : "更新处理状态"}
        onClick={() => onStatusChange(row.id)}
        className="focus-visible:outline-accent-primary inline-flex items-center gap-1 rounded-full focus-visible:outline-2"
      >
        <Badge value={row.status} label={row.statusName} />
        <ChevronDown aria-hidden="true" className="size-3 text-secondary" />
      </button>
    ) : (
      <Badge value={row.status} label={row.statusName} />
    );
  const fieldLabel = (row: Row, field: "severity" | "assignee") => {
    const label = field === "severity" ? "调整严重程度" : "指派负责人";
    const content =
      field === "severity" ? (
        <Badge value={row.severity || "major"} />
      ) : (
        <Badge value={row.values[1] === "未指派" ? "pending" : "in_progress"} label={row.values[1] || "未指派"} />
      );
    return kind === "defects" && onFieldChange && canChangeField?.(row.id, field) ? (
      <button
        type="button"
        aria-label={`${label}：${row.title}`}
        title={label}
        onClick={() => onFieldChange(row.id, field)}
        className="focus-visible:outline-accent-primary inline-flex items-center gap-1 rounded-full focus-visible:outline-2"
      >
        {content}
        <ChevronDown aria-hidden="true" className="size-3 text-secondary" />
      </button>
    ) : (
      content
    );
  };
  const card = (row: Row) => (
    <div className="flex items-start gap-2">
      {onToggle && (
        <input
          className="mt-4 shrink-0"
          type="checkbox"
          aria-label={`选择记录：${row.title}`}
          checked={selectedIds?.includes(row.id) || false}
          onChange={(event) => onToggle(row.id, event.target.checked)}
        />
      )}
      <div className="min-w-0 flex-1 space-y-2 rounded-md border border-subtle bg-surface-1 p-3 hover:bg-layer-1">
        <button
          type="button"
          onClick={() => onOpen(row.id)}
          className="platform-record-link block w-full text-left text-13 break-words"
        >
          {row.code && <span className="font-normal mr-2 inline-block text-11 text-secondary">{row.code}</span>}
          {row.title}
        </button>
        {row.subtitle && <p className="text-11 break-words text-secondary">{row.subtitle}</p>}
        <div className="flex flex-wrap items-center gap-2 text-11">
          {statusLabel(row)}
          {row.severity && fieldLabel(row, "severity")}
          {row.severity && fieldLabel(row, "assignee")}
          <span className="text-secondary">
            {(row.severity ? row.values.slice(2) : row.values).filter(Boolean).join(" · ")}
          </span>
        </div>
        {renderActions && <div className="flex flex-wrap gap-2">{renderActions(row.id)}</div>}
      </div>
    </div>
  );
  if (layout === "board") {
    const groups = [...new Map(rows.map((row) => [row.status, row.statusName])).entries()];
    return (
      <>
        <div aria-label="状态看板" title="本页记录" className="flex min-w-0 gap-4 overflow-x-auto pb-3">
          {groups.map(([status, name]) => (
            <section key={status} className="w-72 shrink-0 space-y-3 rounded-md bg-layer-1 p-3">
              <h2 className="flex items-center justify-between text-13 font-medium">
                <Badge value={status} label={name} />
                <span className="text-11 text-secondary">{rows.filter((row) => row.status === status).length}</span>
              </h2>
              {rows
                .filter((row) => row.status === status)
                .map((row) => (
                  <div key={row.id}>{card(row)}</div>
                ))}
            </section>
          ))}
        </div>
      </>
    );
  }
  if (layout === "table")
    return (
      <div className="max-w-full overflow-x-auto rounded-md border border-subtle">
        <table className="w-full min-w-[600px] text-left text-12">
          <thead className="bg-layer-1 text-secondary">
            <tr>
              {onTogglePage && (
                <th className="w-10 p-3">
                  <input
                    type="checkbox"
                    aria-label="选择本页记录"
                    checked={rows.length > 0 && rows.every((row) => selectedIds?.includes(row.id))}
                    onChange={(event) => onTogglePage(event.target.checked)}
                  />
                </th>
              )}
              <th className="p-3">
                {kind ? <TableHeaderFilter label="标题 / 编号" kind={kind} context={context} /> : "标题 / 编号"}
              </th>
              <th className="p-3">
                {kind ? (
                  <TableHeaderFilter label={kind === "cases" ? "模块" : "状态"} kind={kind} context={context} />
                ) : (
                  "状态"
                )}
              </th>
              {columns.map((column) => (
                <th key={column} className="p-3">
                  {kind ? <TableHeaderFilter label={column} kind={kind} context={context} /> : column}
                </th>
              ))}
              {renderActions && <th className="p-3">操作</th>}
            </tr>
          </thead>
          <tbody>
            {!rows.length && (
              <tr>
                <td
                  colSpan={2 + columns.length + (onTogglePage ? 1 : 0) + (renderActions ? 1 : 0)}
                  className="p-6 text-center text-13 text-secondary"
                  role="status"
                >
                  没有匹配记录，可调整表头筛选条件。
                </td>
              </tr>
            )}
            {rows.map((row) => (
              <tr key={row.id} className="border-t border-subtle hover:bg-layer-1">
                {onToggle && (
                  <td className="p-3">
                    <input
                      type="checkbox"
                      aria-label={`选择记录：${row.title}`}
                      checked={selectedIds?.includes(row.id) || false}
                      onChange={(event) => onToggle(row.id, event.target.checked)}
                    />
                  </td>
                )}
                <td className="max-w-lg p-3">
                  <button
                    type="button"
                    onClick={() => onOpen(row.id)}
                    className="platform-record-link text-left text-13 break-words"
                  >
                    {row.code && (
                      <span className="font-normal mr-2 inline-block text-11 text-secondary">{row.code}</span>
                    )}
                    {row.title}
                  </button>
                  {row.subtitle && <p className="mt-1 text-11 text-secondary">{row.subtitle}</p>}
                </td>
                <td className="p-3 whitespace-nowrap">{statusLabel(row)}</td>
                {columns.map((column, index) => (
                  <td key={column} className="p-3">
                    {column === "严重程度" && row.severity
                      ? fieldLabel(row, "severity")
                      : column === "负责人" && row.severity
                        ? fieldLabel(row, "assignee")
                        : row.values[index] || "—"}
                  </td>
                ))}
                {renderActions && (
                  <td className="p-3">
                    <div className="flex flex-wrap gap-2">{renderActions(row.id)}</div>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  return (
    <div className="space-y-2">
      {rows.map((row) => (
        <div key={row.id}>{card(row)}</div>
      ))}
    </div>
  );
}
