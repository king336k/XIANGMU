import { useEffect, useState } from "react";
import useSWR from "swr";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass } from "./shared";

type Options = { sources: { id: string; label: string }[]; projects: { id: number; name: string; status: string }[] };
export function ProjectSourceFields({ base, project }: { base: string; project: boolean }) {
  const [source, setSource] = useState("");
  const [selected, setSelected] = useState("");
  const { data, error } = useSWR(`${base}integrations/project-options/`, (url: string) =>
    qualityApi.read<Options>(url)
  );
  useEffect(() => {
    if (!source && data?.sources.length === 1) setSource(data.sources[0].id);
  }, [data, source]);
  const {
    data: options,
    error: projectError,
    isLoading,
  } = useSWR(
    project && source ? `${base}integrations/project-options/?source_instance=${encodeURIComponent(source)}` : null,
    (url: string) => qualityApi.read<Options>(url)
  );
  return (
    <>
      <Field label="数据管理平台 *">
        <select
          required
          name="source_instance"
          aria-label="数据管理平台"
          value={source}
          onChange={(event) => {
            setSource(event.target.value);
            setSelected("");
          }}
          className={fieldClass}
        >
          <option value="">
            {data ? (data.sources.length ? "请选择平台连接" : "尚未配置平台连接") : "正在读取平台连接…"}
          </option>
          {data?.sources.map((row) => (
            <option key={row.id} value={row.id}>
              {row.label}
            </option>
          ))}
        </select>
      </Field>
      {project && (
        <Field label="数据管理平台项目 *">
          <select
            required
            name="external_project_id"
            aria-label="数据管理平台项目"
            disabled={!source || isLoading}
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
            className={fieldClass}
          >
            <option value="">
              {!source
                ? "先选择平台"
                : isLoading
                  ? "正在读取项目…"
                  : options?.projects.length
                    ? "请选择项目"
                    : "暂无可关联的项目"}
            </option>
            {options?.projects.map((row) => (
              <option key={row.id} value={row.id}>
                {row.name}（项目编号 {row.id}）
              </option>
            ))}
          </select>
          <input
            type="hidden"
            name="external_project_name"
            value={options?.projects.find((row) => String(row.id) === selected)?.name || ""}
          />
        </Field>
      )}
      {(error || projectError) && (
        <p role="alert" className="text-12 text-danger-primary">
          {errorMessage(error || projectError)}
        </p>
      )}
    </>
  );
}
