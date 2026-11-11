import { useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, Modal, Paging } from "./shared";
import { PagedRecordSelect } from "./paged-record-select";
import type { Page } from "./types";

type Source = { id: string; label: string; source_instance: string; external_project_id: number };
type Snapshot = {
  id: string;
  version: number;
  source_instance: string;
  external_project_id: number;
  status: string;
  created_at: string;
  rows: { id: number; plan_key: string; name: string; description: string; status: string; source_url: string }[];
};
export function ExternalReleasePlans({ base }: { base: string }) {
  const [opening, setOpening] = useState(false);
  const [reading, setReading] = useState(false);
  const [preview, setPreview] = useState<Snapshot>();
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());
  const [page, setPage] = useState(1);
  const { data, error, mutate } = useSWR(
    opening ? `${base}external-release-plans/?page=${page}&per_page=20` : null,
    (url: string) => qualityApi.read<Page<Snapshot>>(url)
  );

  return (
    <>
      <Button variant="neutral-primary" onClick={() => setOpening(true)}>
        外部发布计划
      </Button>
      {opening && (
        <Modal title="外部发布计划" onClose={() => setOpening(false)}>
          <div className="flex flex-wrap justify-between gap-3">
            <p className="text-12 text-secondary">保存来源计划快照，本平台的发布检查单独维护。</p>
            <Button
              variant="neutral-primary"
              onClick={() => {
                setRequestId(crypto.randomUUID());
                setReading(true);
              }}
            >
              读取来源计划
            </Button>
          </div>
          {error && (
            <p role="alert" className="text-13 text-danger-primary">
              {errorMessage(error)}
            </p>
          )}
          {data?.results.map((row) => (
            <article key={row.id} className="rounded border border-subtle p-3 text-13">
              <p>
                {row.source_instance} · 项目 {row.external_project_id} · {row.rows.length} 项{" "}
                <span className="text-12 text-secondary">{row.status === "confirmed" ? "已确认快照" : "待核对"}</span>
              </p>
              <Button variant="neutral-primary" onClick={() => setPreview(row)}>
                查看计划
              </Button>
            </article>
          ))}
          {data && !data.count && <p className="text-13 text-secondary">暂无同步记录</p>}
          {data && <Paging page={page} count={data.count} perPage={20} onChange={setPage} />}
        </Modal>
      )}
      {reading && (
        <Modal
          title="读取来源计划"
          onClose={() => setReading(false)}
          submitLabel="读取预览"
          onSubmit={async (form) => {
            const value = await qualityApi.write<Snapshot>(`${base}external-release-plans/preview/`, {
              mapping_id: form.get("source"),
              request_id: requestId,
            });
            setPreview(value);
            await mutate();
          }}
        >
          <Field label="已关联的来源项目 *">
            <PagedRecordSelect<Source>
              url={`${base}external-release-plans/preview/`}
              name="source"
              placeholder="选择来源项目"
              getLabel={(row) => row.label}
            />
          </Field>
        </Modal>
      )}
      {preview && (
        <Modal
          title="来源计划快照"
          onClose={() => setPreview(undefined)}
          submitLabel="确认保存快照"
          onSubmit={
            preview.status === "preview"
              ? async () => {
                  await qualityApi.write(`${base}external-release-plans/${preview.id}/confirm/`, {
                    expected_version: preview.version,
                  });
                  await mutate();
                }
              : undefined
          }
        >
          <p className="text-12 text-secondary">
            {preview.source_instance} · 来源项目 {preview.external_project_id}
          </p>
          <div className="max-h-96 space-y-3 overflow-auto">
            {preview.rows.map((row) => (
              <article key={row.id} className="rounded border border-subtle p-3 text-13">
                <p className="font-medium">
                  {row.plan_key} · {row.name}
                </p>
                <p className="mt-1 whitespace-pre-wrap text-secondary">{row.description}</p>
                <p className="mt-1 text-12 text-secondary">
                  来源状态：
                  {(
                    {
                      DRAFT: "草稿",
                      SYNCED: "已同步",
                      PLANNED: "已计划",
                      READY: "已就绪",
                      RELEASED: "已发布",
                      CANCELLED: "已取消",
                    } as Record<string, string>
                  )[row.status] || "来源自定义状态"}
                </p>
                {row.source_url && (
                  <a
                    href={row.source_url}
                    rel="noopener noreferrer"
                    target="_blank"
                    className="mt-2 inline-block text-12 text-accent-primary"
                  >
                    查看来源文档 ↗
                  </a>
                )}
              </article>
            ))}
          </div>
        </Modal>
      )}
    </>
  );
}
