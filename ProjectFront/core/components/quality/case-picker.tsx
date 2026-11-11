// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass, Paging } from "./shared";
import { mergeCaseSelection } from "./case-selection";
import type { CaseOption } from "./case-selection";
import type { Page } from "./types";
import { priorityNames } from "./types";
type OptionsPage = Page<CaseOption> & { modules: { module: string; count: number }[] };

export function CasePicker({
  base,
  selected,
  onChange,
}: {
  base: string;
  selected: CaseOption[];
  onChange: (rows: CaseOption[]) => void;
}) {
  const [search, setSearch] = useState(""),
    [module, setModule] = useState(""),
    [priority, setPriority] = useState(""),
    [page, setPage] = useState(1),
    [perPage, setPerPage] = useState(25),
    [selectedOnly, setSelectedOnly] = useState(false),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  const filterParams = {
    search,
    module: module === "__empty__" ? "" : module,
    module_empty: String(module === "__empty__"),
    priority,
  };
  const query = new URLSearchParams({ ...filterParams, per_page: String(perPage), page: String(page) });
  const { data, error, isLoading, isValidating } = useSWR(
    `${base}case-options/?${query}`,
    (url: string) => qualityApi.read<OptionsPage>(url),
    { keepPreviousData: true }
  );
  const ids = new Set(selected.map((row) => row.id));
  const chosen = selected.filter(
    (row) =>
      (!search.trim() ||
        `${row.code || ""} ${row.title} ${row.module} ${row.requirement_title || ""}`
          .toLocaleLowerCase()
          .includes(search.trim().toLocaleLowerCase())) &&
      (!module || (module === "__empty__" ? !row.module : row.module === module)) &&
      (!priority || row.priority === priority)
  );
  const count = selectedOnly ? chosen.length : data?.count || 0;
  useEffect(() => {
    if (selectedOnly) setPage((current) => Math.min(current, Math.max(1, Math.ceil(chosen.length / perPage))));
  }, [selectedOnly, chosen.length, perPage]);
  const rows = selectedOnly ? chosen.slice((page - 1) * perPage, page * perPage) : data?.results || [];
  const allPage = rows.length > 0 && rows.every((row) => ids.has(row.id));
  const update = (items: CaseOption[], checked: boolean) => {
    try {
      onChange(mergeCaseSelection(selected, items, checked));
      setMessage("");
    } catch (cause) {
      setMessage(errorMessage(cause));
    }
  };
  const selectMatching = async () => {
    setBusy(true);
    setMessage("");
    try {
      const response = await qualityApi.read<{ results: CaseOption[] }>(
        `${base}case-options/?${new URLSearchParams({ ...filterParams, selection: "true" })}`
      );
      update(response.results, true);
    } catch (cause) {
      setMessage(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  };
  return (
    <fieldset className="min-w-0 space-y-3 rounded-md border border-subtle p-3">
      <legend className="px-1 text-13 font-medium">选择测试用例 · 已选 {selected.length}/500</legend>
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,0.8fr)_minmax(0,0.6fr)]">
        <Field label="搜索用例">
          <input
            type="search"
            disabled={busy}
            value={search}
            maxLength={255}
            className={fieldClass}
            placeholder={selectedOnly ? "查找已选标题或模块" : "标题、模块或前置条件"}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
          />
        </Field>
        <Field label="用例模块">
          <select
            value={module}
            disabled={busy}
            className={fieldClass}
            onChange={(event) => {
              setModule(event.target.value);
              setPage(1);
            }}
          >
            <option value="">全部模块</option>
            {data?.modules.map((row) => (
              <option key={row.module} value={row.module || "__empty__"}>
                {row.module || "未分模块"}（{row.count}）
              </option>
            ))}
          </select>
        </Field>
        <Field label="用例优先级">
          <select
            value={priority}
            disabled={busy}
            className={fieldClass}
            onChange={(event) => {
              setPriority(event.target.value);
              setPage(1);
            }}
          >
            <option value="">全部优先级</option>
            {Object.entries(priorityNames).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-12">
        <Button
          type="button"
          variant="neutral-primary"
          disabled={!rows.length || busy || isLoading || isValidating}
          onClick={() => update(rows, !allPage)}
        >
          {allPage ? "取消选择本页" : "选择本页"}
        </Button>
        {!selectedOnly && (
          <Button
            type="button"
            variant="neutral-primary"
            disabled={busy || isLoading || isValidating || !data?.count}
            onClick={() => void selectMatching()}
          >
            选择全部筛选结果（{data?.count || 0}）
          </Button>
        )}
        <label className="flex items-center gap-1.5">
          <input
            type="checkbox"
            checked={selectedOnly}
            disabled={busy}
            onChange={(event) => {
              setSelectedOnly(event.target.checked);
              setPage(1);
            }}
          />
          仅看已选（{selected.length}）
        </label>
        <Button
          type="button"
          variant="neutral-primary"
          disabled={!selected.length || busy}
          onClick={() => {
            onChange([]);
            setPage(1);
          }}
        >
          清空已选
        </Button>
      </div>
      {(error || message) && (
        <p role="alert" className="text-12 text-danger-primary">
          {message || errorMessage(error)}
        </p>
      )}
      <div
        className="max-h-80 min-w-0 overflow-auto rounded border border-subtle"
        aria-busy={isLoading || isValidating}
      >
        <table className="w-full table-fixed text-left text-12">
          <thead className="sticky top-0 z-10 bg-layer-1">
            <tr>
              <th className="w-9 p-2">
                <input
                  type="checkbox"
                  aria-label="选择本页全部用例"
                  checked={allPage}
                  disabled={!rows.length || busy || isLoading || isValidating}
                  onChange={(event) => update(rows, event.target.checked)}
                  ref={(element) => {
                    if (element) element.indeterminate = !allPage && rows.some((row) => ids.has(row.id));
                  }}
                />
              </th>
              <th className="p-2">用例标题</th>
              <th className="w-28 p-2">模块</th>
              <th className="w-14 p-2">优先级</th>
              <th className="w-12 p-2">版本</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className={`border-t border-subtle ${ids.has(row.id) ? "bg-layer-1" : ""}`}>
                <td className="p-2 align-top">
                  <input
                    type="checkbox"
                    aria-label={`选择用例：${row.title}`}
                    checked={ids.has(row.id)}
                    disabled={busy || isLoading || isValidating}
                    onChange={(event) => update([row], event.target.checked)}
                  />
                </td>
                <td className="p-2 break-words">
                  <button
                    type="button"
                    className="text-left hover:text-accent-primary"
                    disabled={busy || isLoading || isValidating}
                    onClick={() => update([row], !ids.has(row.id))}
                  >
                    {row.code && <span className="mr-2 text-11 text-secondary">{row.code}</span>}
                    {row.title}
                  </button>
                  {row.requirement_title && (
                    <p className="mt-1 truncate text-tertiary">需求：{row.requirement_title}</p>
                  )}
                </td>
                <td className="p-2 break-words text-secondary">{row.module || "未分模块"}</td>
                <td className="p-2">{priorityNames[row.priority] || row.priority}</td>
                <td className="p-2">v{selected.find((item) => item.id === row.id)?.version || row.version}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {isLoading && (
          <p role="status" className="p-4 text-12 text-secondary">
            正在读取用例…
          </p>
        )}
        {!isLoading && !rows.length && (
          <p className="p-4 text-12 text-secondary">
            {selectedOnly ? "当前筛选下没有已选用例。" : "当前筛选没有可选用例，请调整条件。"}
          </p>
        )}
      </div>
      <Paging
        page={page}
        count={count}
        perPage={perPage}
        pageSizes={[25, 50, 100]}
        onChange={(value) => {
          if (!busy && !isLoading && !isValidating) setPage(value);
        }}
        onPageSizeChange={(size) => {
          if (!busy) {
            setPerPage(size);
            setPage(1);
          }
        }}
      />
      <p className="text-11 text-secondary">
        创建时固定当前用例版本；编辑用例集时保留原有版本。未选择的其他页面不会被自动加入。
      </p>
    </fieldset>
  );
}
