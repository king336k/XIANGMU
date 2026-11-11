// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass } from "./shared";

type Attachment = { id: string; name: string; size: number; sha256: string };
export function AttachmentUpload({
  base,
  packageId,
  canUpload,
  paths,
}: {
  base: string;
  packageId: string;
  canUpload: boolean;
  paths: string[];
}) {
  const url = `${base}packages/${packageId}/files/`;
  const { data, error, mutate } = useSWR(url, (key: string) => qualityApi.read<Attachment[]>(key));
  const [manifestPath, setManifestPath] = useState(paths[0] || "");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  return (
    <div className="mt-3 space-y-3 border-t border-subtle pt-3">
      {data?.map((file) => (
        <div key={file.id} className="flex flex-wrap items-center justify-between gap-2 text-12">
          <span>
            {file.name} · {file.size} 字节 · 文件已校验
          </span>
          <Button
            type="button"
            variant="neutral-primary"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setActionError("");
              try {
                await qualityApi.download(`${base}files/${file.id}/download/`, file.name);
              } catch (e) {
                setActionError(errorMessage(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            下载
          </Button>
        </div>
      ))}
      {canUpload && (
        <div className="space-y-3">
          <Field label="清单文件路径">
            <select
              value={manifestPath}
              onChange={(event) => setManifestPath(event.target.value)}
              className={fieldClass}
            >
              {paths.map((path) => (
                <option key={path} value={path}>
                  {path}
                </option>
              ))}
            </select>
          </Field>
          <Field label="上传清单中的诊断文件（单文件20MB以内）">
            <input
              type="file"
              disabled={busy}
              className={fieldClass}
              onChange={async (event) => {
                const file = event.target.files?.[0];
                if (!file) return;
                setActionError("");
                if (file.size > 20 * 1024 * 1024) {
                  setActionError("单个诊断文件不能超过20MB。");
                  return;
                }
                setBusy(true);
                try {
                  const form = new FormData();
                  form.append("file", file);
                  form.append("manifest_path", manifestPath);
                  await qualityApi.write(url, form);
                  await mutate();
                } catch (e) {
                  setActionError(errorMessage(e));
                } finally {
                  setBusy(false);
                  event.target.value = "";
                }
              }}
            />
          </Field>
        </div>
      )}
      {(error || actionError) && (
        <p role="alert" className="text-12 text-danger-primary">
          {actionError || errorMessage(error)}
        </p>
      )}
      {busy && (
        <p role="status" className="text-12 text-secondary">
          正在传输并核对文件…
        </p>
      )}
    </div>
  );
}
