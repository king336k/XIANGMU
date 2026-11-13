import { RoundOwnerSummary } from "./round-owner-summary";
import { useState } from "react";
import useSWR from "swr";
import { qualityApi, errorMessage } from "./api";
import { Badge, Field, fieldClass, Paging } from "./shared";
import { VerificationRoundView } from "./verification-round-view";
import { verificationStatus, verificationStatusTone } from "./verification-types";
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
                <span className="inline-flex w-[calc(100%-1.5rem)] flex-wrap items-center gap-x-3 gap-y-2 align-middle">
                  <span className="min-w-0 flex-1 font-medium break-words">
                    <span className="text-accent-primary">{row.code}</span>
                    {row.code ? " · " : ""}
                    {row.title}
                  </span>
                  {row.current && (
                    <span className="inline-flex flex-wrap items-center gap-2">
                      <span className="text-12 text-secondary">第 {row.current.round_no} 轮</span>
                      <Badge value="neutral" label={`版本 ${row.current.fixed_build}`} />
                      <Badge
                        value={verificationStatusTone[row.current.execution_state || row.current.status] || "neutral"}
                        label={`${row.defect_status === "resolved" && ["returned_repair", "reopened", "superseded"].includes(row.current.status) ? "上轮：" : ""}${verificationStatus[row.current.execution_state || row.current.status] || row.current.status}`}
                      />
                      <Badge
                        value={row.current.summary.passed ? "passed" : "neutral"}
                        label={`通过 ${row.current.summary.passed}/${row.current.summary.total}`}
                      />
                      {row.current.summary.failed > 0 && (
                        <Badge value="failed" label={`失败 ${row.current.summary.failed}`} />
                      )}
                      {row.current.summary.pending > 0 && (
                        <Badge value="pending" label={`未执行 ${row.current.summary.pending}`} />
                      )}
                      {row.current.summary.blocked > 0 && (
                        <Badge value="blocked" label={`受阻 ${row.current.summary.blocked}`} />
                      )}
                      {row.current.summary.inconclusive > 0 && (
                        <Badge value="inconclusive" label={`无法判定 ${row.current.summary.inconclusive}`} />
                      )}
                      {row.current.summary.skipped > 0 && (
                        <Badge value="neutral" label={`跳过 ${row.current.summary.skipped}`} />
                      )}
                    </span>
                  )}
                </span>
              </summary>
              <div className="mt-3 space-y-3">
                {row.current && !["returned_repair", "reopened", "superseded"].includes(row.current.status) && (
                  <RoundOwnerSummary base={base} verificationId={row.current.id} mode={row.current.mode} />
                )}
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
