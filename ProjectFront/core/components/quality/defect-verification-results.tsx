import { useState } from "react";
import useSWR from "swr";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass, Paging } from "./shared";
import { VerificationRoundView } from "./verification-round-view";
import { verificationStatus } from "./verification-types";
import type { VerificationData } from "./verification-types";
import type { Page } from "./types";
import { ProjectRouteLink } from "@/components/common/project-route-link";
export function DefectVerificationResults({ base, projectUrl }: { base: string; projectUrl: string }) {
  const [page, setPage] = useState(1),
    [search, setSearch] = useState("");
  const query = new URLSearchParams({ page: String(page), per_page: "20", search });
  const { data, error } = useSWR(`${base}verification-results/?${query}`, (url: string) =>
    qualityApi.read<Page<VerificationData & { title: string; code?: string }>>(url)
  );
  return (
    <section className="space-y-4">
      <Field label="搜索缺陷">
        <input
          type="search"
          className={`${fieldClass} max-w-lg`}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setPage(1);
          }}
        />
      </Field>
      {error ? (
        <p role="alert" className="text-13 text-danger-primary">
          {errorMessage(error)}
        </p>
      ) : !data ? (
        <p role="status" className="text-13 text-secondary">
          正在加载…
        </p>
      ) : !data.results.length ? (
        <p className="text-13 text-secondary">暂无缺陷验证记录。</p>
      ) : (
        <div className="space-y-2">
          {data.results.map((row) => (
            <details key={row.defect_id} className="rounded border border-subtle p-3">
              <summary className="cursor-pointer text-13">
                {row.code ? `${row.code} · ` : ""}
                {row.title}
                {row.current && (
                  <span className="ml-3 text-12 text-secondary">
                    第 {row.current.round_no} 轮 · {row.current.fixed_build} ·{" "}
                    {verificationStatus[row.current.status] || row.current.status} · 通过 {row.current.summary.passed}/
                    {row.current.summary.total}
                  </span>
                )}
              </summary>
              <div className="mt-3 space-y-3">
                {row.current && <VerificationRoundView round={row.current} />}
                <ProjectRouteLink
                  to={`${projectUrl}/defects/?defect=${row.defect_id}`}
                  className="text-13 text-accent-primary"
                >
                  查看缺陷
                </ProjectRouteLink>
              </div>
            </details>
          ))}
        </div>
      )}
      {data && <Paging page={page} perPage={20} count={data.count} onChange={setPage} />}
    </section>
  );
}
