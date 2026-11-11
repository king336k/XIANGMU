import { useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "../quality/api";
import { Field, fieldClass, Modal, Paging } from "../quality/shared";
import { PagedRecordSelect } from "../quality/paged-record-select";
import type { Page } from "../quality/types";

type Share = {
  id: string;
  target_project_id: string;
  target_project_name: string;
  publication_version: number;
  version: number;
  active: boolean;
  effective: boolean;
  device_scope: string;
  version_scope: string;
  reason: string;
};
export function SharingPanel({
  base,
  articleId,
  version,
  onClose,
}: {
  base: string;
  articleId: string;
  version: number;
  onClose: () => void;
}) {
  const [granting, setGranting] = useState(false);
  const [regrant, setRegrant] = useState<Share>();
  const [withdrawing, setWithdrawing] = useState<Share>();
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(20);
  const { data, error, mutate } = useSWR(
    `${base}articles/${articleId}/shares/?page=${page}&per_page=${perPage}`,
    (url: string) => qualityApi.read<Page<Share>>(url)
  );
  return (
    <>
      <Modal title="共享范围" onClose={onClose}>
        <div className="flex items-center justify-between gap-3">
          <p className="text-12 text-secondary">仅共享所选发布版，原文附件保留在本项目。</p>
          <Button
            variant="neutral-primary"
            onClick={() => {
              setRegrant(undefined);
              setGranting(true);
            }}
          >
            添加项目
          </Button>
        </div>
        {error && (
          <p role="alert" className="text-13 text-danger-primary">
            {errorMessage(error)}
          </p>
        )}
        {data && !data.count && <p className="text-13 text-secondary">尚未共享</p>}
        <div className="divide-y divide-subtle">
          {data?.results.map((row) => (
            <article key={row.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
              <div className="min-w-0 text-13">
                <p className="font-medium break-words">
                  {row.target_project_name}{" "}
                  <span className="font-normal text-12 text-secondary">· v{row.publication_version}</span>
                </p>
                <p className="mt-1 text-12 text-secondary">
                  {row.effective ? "共享中" : row.active ? "来源已更新或失效" : "已撤回"}
                  {row.device_scope ? ` · ${row.device_scope}` : ""}
                  {row.version_scope ? ` · ${row.version_scope}` : ""}
                </p>
              </div>
              {!row.active && (
                <Button
                  variant="neutral-primary"
                  onClick={() => {
                    setRegrant(row);
                    setGranting(true);
                  }}
                >
                  重新授权
                </Button>
              )}
              {row.active && (
                <Button variant="neutral-primary" onClick={() => setWithdrawing(row)}>
                  撤回
                </Button>
              )}
            </article>
          ))}
        </div>
        {data && (
          <Paging
            page={page}
            count={data.count}
            perPage={perPage}
            onChange={setPage}
            onPageSizeChange={(size) => {
              setPerPage(size);
              setPage(1);
            }}
          />
        )}
      </Modal>
      {granting && (
        <Modal
          title="添加共享项目"
          onClose={() => setGranting(false)}
          submitLabel="授权共享"
          onSubmit={async (form) => {
            await qualityApi.write(`${base}articles/${articleId}/shares/`, {
              target_project_id: regrant?.target_project_id || form.get("target_project_id"),
              expected_version: version,
              ...(regrant ? { expected_share_version: regrant.version } : {}),
              reason: form.get("reason"),
              device_scope: form.get("device_scope"),
              version_scope: form.get("version_scope"),
            });
            await mutate();
          }}
        >
          <Field label="目标项目 *">
            {regrant ? (
              <p className="text-13">{regrant.target_project_name}</p>
            ) : (
              <PagedRecordSelect<{ id: string; name: string; identifier: string }>
                url={`${base}share-targets/`}
                name="target_project_id"
                placeholder="选择有管理权限的项目"
                getLabel={(row) => `${row.identifier} · ${row.name}`}
              />
            )}
          </Field>
          <Field label="共享说明 *">
            <textarea name="reason" required maxLength={4000} rows={2} className={fieldClass} />
          </Field>
          <details className="rounded border border-subtle p-3">
            <summary className="cursor-pointer text-13">适用范围（可选）</summary>
            <div className="mt-3 space-y-3">
              <Field label="设备或场景">
                <input name="device_scope" maxLength={255} className={fieldClass} />
              </Field>
              <Field label="适用版本">
                <input name="version_scope" maxLength={255} className={fieldClass} />
              </Field>
            </div>
          </details>
        </Modal>
      )}
      {withdrawing && (
        <Modal
          title="撤回共享"
          onClose={() => setWithdrawing(undefined)}
          submitLabel="撤回共享"
          onSubmit={async (form) => {
            await qualityApi.write(`${base}shares/${withdrawing.id}/withdraw/`, {
              expected_version: withdrawing.version,
              reason: form.get("reason"),
            });
            await mutate();
          }}
        >
          <p className="text-13">{withdrawing.target_project_name} 将停止检索此知识。</p>
          <Field label="撤回原因 *">
            <textarea required name="reason" maxLength={4000} rows={2} className={fieldClass} />
          </Field>
        </Modal>
      )}
    </>
  );
}
