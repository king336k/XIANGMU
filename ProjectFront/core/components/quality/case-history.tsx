import { v4 as uuidv4 } from "uuid";
// SPDX-License-Identifier: AGPL-3.0-only
import { orderBy } from "lodash-es";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { renderNumericDateTime } from "@plane/utils";
import { qualityApi, errorMessage } from "./api";
import { Modal } from "./shared";
import type { TestCase, Revision } from "./types";
export function CaseHistory({
  base,
  value,
  onClose,
  currentOnly = false,
}: {
  base: string;
  value: TestCase;
  onClose: () => void;
  currentOnly?: boolean;
}) {
  const { data, error } = useSWR(`${base}cases/${value.id}/`, (url: string) =>
    qualityApi.read<TestCase & { revisions: Revision[] }>(url)
  );
  const [selected, setSelected] = useState<number>();
  const revisions = data?.revisions || [];
  const sorted = orderBy(revisions, ["version"], ["desc"]);
  const revision = sorted.find((row) => row.version === selected) || sorted[0];
  const snapshot = revision?.snapshot || data || value;
  const steps = useMemo(() => snapshot.steps.map((step) => ({ ...step, localId: uuidv4() })), [snapshot.steps]);
  return (
    <Modal title={currentOnly ? value.title : `用例历史 · ${value.title}`} width="wide" onClose={onClose}>
      <p className="text-11 text-secondary">
        {value.code ? `${value.code} · ` : ""}创建人：{value.created_by_name || "未记录"}
      </p>
      {error && (
        <p role="alert" className="text-danger-primary">
          {errorMessage(error)}
        </p>
      )}
      <div className={`grid min-w-0 gap-4 ${currentOnly ? "" : "md:grid-cols-[12rem_minmax(0,1fr)]"}`}>
        {!currentOnly && (
          <nav
            aria-label="用例版本历史"
            className="flex max-h-96 flex-wrap content-start gap-1 overflow-y-auto md:flex-col"
          >
            {sorted.map((row) => (
              <button
                type="button"
                key={row.id}
                onClick={() => setSelected(row.version)}
                aria-current={revision?.version === row.version ? "true" : undefined}
                className={`platform-selection-item rounded px-3 py-2 text-left ${revision?.version === row.version ? "bg-accent-subtle text-accent-primary" : "hover:bg-layer-1"}`}
              >
                <span className="text-12 font-medium">
                  v{row.version}
                  {row.version === data?.version ? " · 当前" : ""}
                </span>
                <span className="mt-1 block text-10 text-secondary">{renderNumericDateTime(row.created_at)}</span>
              </button>
            ))}
          </nav>
        )}
        <article className="platform-record-section min-w-0 space-y-4">
          <div>
            <p className="text-11 text-secondary">
              v{revision?.version || value.version}
              {revision ? ` · ${renderNumericDateTime(revision.created_at)}` : ""}
            </p>
            <h3 className="mt-1 text-14 font-medium">{revision?.title || snapshot.title}</h3>
          </div>
          {snapshot.preconditions && (
            <section>
              <h4 className="text-12 font-medium text-secondary">前置条件</h4>
              <p className="mt-2 text-13 whitespace-pre-wrap">{snapshot.preconditions}</p>
            </section>
          )}
          <div className="overflow-x-auto rounded-md border border-subtle">
            <table className="w-full text-left text-12">
              <thead className="bg-layer-1 text-secondary">
                <tr>
                  <th className="w-12 p-3">序号</th>
                  <th className="p-3">操作步骤</th>
                  <th className="p-3">预期结果</th>
                </tr>
              </thead>
              <tbody>
                {steps.map((step, index) => (
                  <tr key={step.localId} className="border-t border-subtle align-top">
                    <td className="p-3 text-secondary">{index + 1}</td>
                    <td className="p-3 whitespace-pre-wrap">{step.action}</td>
                    <td className="p-3 whitespace-pre-wrap">{step.expected}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      </div>
    </Modal>
  );
}
