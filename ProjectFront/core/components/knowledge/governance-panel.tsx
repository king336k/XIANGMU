import { SemanticIndexPanel } from "./semantic-index-panel";
// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "../quality/api";
import { Field, fieldClass, Modal } from "../quality/shared";
type Candidate = { id: string; title: string; status: string; version: number };
type Overview = {
  total: number;
  published: number;
  review: number;
  merged: number;
  candidates: Candidate[][];
  scope: string;
  semantic_candidates?: { source: Candidate; target: Candidate; similarity: number; basis: string }[];
  merge_history?: { id: string; source_title: string; target_title: string; can_undo: boolean }[];
};
export function GovernancePanel({ base, isManager }: { base: string; isManager: boolean }) {
  const [threshold, setThreshold] = useState("0.88");
  const [retaining, setRetaining] = useState<{ source: Candidate; target: Candidate }>();
  const [undoing, setUndoing] = useState<string>();
  const { data, error, mutate } = useSWR(`${base}governance/?semantic_threshold=${threshold}`, (url: string) =>
    qualityApi.read<Overview>(url)
  );
  const [group, setGroup] = useState<Candidate[]>();
  const [sourceId, setSourceId] = useState("");
  const [targetId, setTargetId] = useState("");
  const selectedIds = [sourceId, targetId].filter((id, index, all) => id && all.indexOf(id) === index);
  const { data: comparison, error: compareError } = useSWR(
    group && selectedIds.length ? `${base}governance/compare/${selectedIds.join(",")}` : null,
    async () =>
      Promise.all(
        (group || [])
          .filter((row) => selectedIds.includes(row.id))
          .map((row) => qualityApi.read<{ id: string; title: string; content: string }>(`${base}articles/${row.id}/`))
      )
  );
  return (
    <section className="space-y-5">
      <h2 className="text-18 font-semibold">知识管理</h2>
      <SemanticIndexPanel base={base} />
      {error && (
        <p role="alert" className="text-13 text-danger-primary">
          {errorMessage(error)}
        </p>
      )}
      {data && (
        <>
          <div className="flex flex-wrap gap-6 text-13">
            <span>全部知识 {data.total}</span>
            <span>有效发布 {data.published}</span>
            <span>待审核 {data.review}</span>
            <span>已归并 {data.merged}</span>
          </div>
          <p className="text-12 text-secondary">{data.scope}</p>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-14 font-medium">相似内容</h3>
            <label className="flex items-center gap-2 text-12 text-secondary">
              相似度阈值
              <select
                aria-label="治理相似度阈值"
                className={fieldClass}
                value={threshold}
                onChange={(event) => setThreshold(event.target.value)}
              >
                {["0.85", "0.88", "0.92", "0.95"].map((value) => (
                  <option key={value} value={value}>
                    {Number(value) * 100}%
                  </option>
                ))}
              </select>
            </label>
          </div>
          {!data.semantic_candidates?.length && (
            <p className="text-13 text-secondary">暂无相似候选；可在上方更新索引。</p>
          )}
          {data.semantic_candidates?.map((pair) => (
            <article
              key={`${pair.source.id}-${pair.target.id}`}
              className="space-y-3 rounded-md border border-subtle p-4"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="min-w-0 text-13 font-medium break-words">
                  {pair.source.title} / {pair.target.title}
                </p>
                <span className="text-12 text-secondary">相似度 {Math.round(pair.similarity * 100)}%</span>
              </div>
              <p className="text-12 text-secondary">{pair.basis}</p>
              {isManager && (
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="neutral-primary"
                    onClick={() => {
                      setSourceId(pair.source.id);
                      setTargetId(pair.target.id);
                      setGroup([pair.source, pair.target]);
                    }}
                  >
                    比较正文
                  </Button>
                  <Button variant="neutral-primary" onClick={() => setRetaining(pair)}>
                    保留两条
                  </Button>
                </div>
              )}
            </article>
          ))}
          <h3 className="text-14 font-medium">同标题候选</h3>
          {!data.candidates.length && (
            <p className="text-13 text-secondary">没有发现标题相同的候选。内容不同的知识仍需人工评估。</p>
          )}
          {data.candidates.map((rows) => (
            <article
              key={rows[0].id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-subtle p-4"
            >
              <div>
                <h4 className="text-13 font-medium">{rows[0].title}</h4>
                <p className="mt-1 text-12 text-secondary">{rows.length}条同标题知识 · 逐条保留历史版本</p>
              </div>
              {isManager && (
                <Button
                  variant="neutral-primary"
                  onClick={() => {
                    setSourceId("");
                    setTargetId("");
                    setGroup(rows);
                  }}
                >
                  比较后归并
                </Button>
              )}
            </article>
          ))}
        </>
      )}
      {!!data?.merge_history?.length && (
        <details className="rounded-md border border-subtle p-3">
          <summary className="cursor-pointer text-13">归并记录</summary>
          <div className="mt-3 divide-y divide-subtle">
            {data.merge_history.map((row) => (
              <div key={row.id} className="flex flex-wrap items-center justify-between gap-3 py-3 text-13">
                <span>
                  {row.source_title} → {row.target_title}
                </span>
                {isManager && row.can_undo && (
                  <Button variant="neutral-primary" onClick={() => setUndoing(row.id)}>
                    撤回归并
                  </Button>
                )}
              </div>
            ))}
          </div>
        </details>
      )}
      {retaining && (
        <Modal
          title="保留两条知识"
          onClose={() => setRetaining(undefined)}
          submitLabel="保留两条"
          onSubmit={async (form) => {
            await qualityApi.write(`${base}governance/ignore/`, {
              source_id: retaining.source.id,
              target_id: retaining.target.id,
              source_version: retaining.source.version,
              target_version: retaining.target.version,
              reason: form.get("reason"),
            });
            await mutate();
          }}
        >
          <Field label="保留原因 *">
            <textarea required name="reason" maxLength={4000} className={fieldClass} rows={2} />
          </Field>
        </Modal>
      )}
      {undoing && (
        <Modal
          title="撤回归并"
          onClose={() => setUndoing(undefined)}
          submitLabel="撤回归并"
          onSubmit={async (form) => {
            await qualityApi.write(`${base}governance/merges/${undoing}/undo/`, { reason: form.get("reason") });
            await mutate();
          }}
        >
          <p className="text-12 text-secondary">恢复为两条草稿，核对后分别发布。</p>
          <Field label="撤回原因 *">
            <textarea required name="reason" maxLength={4000} className={fieldClass} rows={2} />
          </Field>
        </Modal>
      )}
      {group && (
        <Modal
          title="知识归并"
          onClose={() => setGroup(undefined)}
          onSubmit={async (form) => {
            const source = group.find((row) => row.id === form.get("source_id")),
              target = group.find((row) => row.id === form.get("target_id"));
            if (!source || !target || source.id === target.id) throw new Error("请选择两条不同的知识。");
            if (
              compareError ||
              !comparison?.some((row) => row.id === source.id) ||
              !comparison.some((row) => row.id === target.id)
            )
              throw new Error("请等两条知识正文读取完成后核对再归并。");
            await qualityApi.write(`${base}governance/merge/`, {
              source_id: source.id,
              target_id: target.id,
              source_version: source.version,
              target_version: target.version,
              reason: form.get("reason"),
            });
            await mutate();
          }}
        >
          <div className="grid max-h-64 gap-3 overflow-auto sm:grid-cols-2">
            {comparison?.map((row) => (
              <div key={row.id} className="rounded border border-subtle p-3 text-12">
                <h4 className="font-medium">
                  {row.title} · {row.id.slice(0, 8)}
                </h4>
                <p className="mt-2 whitespace-pre-wrap">{row.content}</p>
              </div>
            ))}
          </div>
          {compareError && (
            <p role="alert" className="text-12 text-danger-primary">
              {errorMessage(compareError)}
            </p>
          )}
          <Field label="来源知识（归并后下线） *">
            <select
              required
              name="source_id"
              value={sourceId}
              onChange={(event) => setSourceId(event.target.value)}
              className={fieldClass}
            >
              <option value="">请选择</option>
              {group.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.title} · {row.id.slice(0, 8)} · v{row.version}
                </option>
              ))}
            </select>
          </Field>
          <Field label="目标知识（形成待审核草稿） *">
            <select
              required
              name="target_id"
              value={targetId}
              onChange={(event) => setTargetId(event.target.value)}
              className={fieldClass}
            >
              <option value="">请选择</option>
              {group.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.title} · {row.id.slice(0, 8)} · v{row.version}
                </option>
              ))}
            </select>
          </Field>
          <Field label="归并理由 *">
            <textarea required name="reason" rows={3} maxLength={4000} className={fieldClass} />
          </Field>
          <p className="text-12 text-secondary">
            历史发布版本保留；来源立即退出检索，目标形成草稿并重新扫描、审核。不会自动发布新增内容。
          </p>
        </Modal>
      )}
    </section>
  );
}
