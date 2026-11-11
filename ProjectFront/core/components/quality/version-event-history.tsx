// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { renderNumericDateTime } from "@plane/utils";
import { qualityApi, errorMessage } from "./api";
import { Paging } from "./shared";
import { useCollectionPagination } from "./use-collection-pagination";
import { versionStatuses } from "./version-types";
import type { VersionDetail } from "./version-types";

export function VersionEventHistory({ base, version }: { base: string; version: VersionDetail }) {
  const [open, setOpen] = useState(false);
  const pagination = useCollectionPagination(`${base}:version-history:${version.id}`);
  const { data, error } = useSWR(
    open ? [`${base}versions/${version.id}/?${pagination.query}`, version.edit_version] : null,
    ([url]: [string, number]) => qualityApi.read<VersionDetail>(url)
  );
  return (
    <details className="text-12 text-secondary" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="cursor-pointer">
        流转记录 · {data?.event_pagination.count ?? version.event_pagination.count}
      </summary>
      {error && (
        <p role="alert" className="mt-3 text-danger-primary">
          {errorMessage(error)}
        </p>
      )}
      {open && !data && !error && (
        <p role="status" className="mt-3">
          正在读取…
        </p>
      )}
      {data && (
        <>
          <ol className="mt-3 space-y-3" aria-label="版本流转记录">
            {data.events.map((item) => (
              <li key={item.id} className="border-l-2 border-subtle pl-3">
                <p>{item.note}</p>
                <p className="mt-1 text-11 text-tertiary">
                  {item.actor} · {renderNumericDateTime(item.created_at)} · {versionStatuses[item.status]}
                </p>
              </li>
            ))}
          </ol>
          {!data.event_pagination.count && <p className="mt-3">暂无流转记录。</p>}
          <Paging {...pagination.paging} count={data.event_pagination.count} />
        </>
      )}
    </details>
  );
}
