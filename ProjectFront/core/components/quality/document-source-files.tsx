// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useState } from "react";
import { Button } from "@plane/ui";
import type { DocumentSourceFile } from "@/components/knowledge/types";
import { errorMessage, qualityApi } from "./api";

export function DocumentSourceFiles({ files }: { files: DocumentSourceFile[] }) {
  const [error, setError] = useState("");
  const [image, setImage] = useState<{ url: string; name: string }>();
  const [busy, setBusy] = useState(false);
  useEffect(
    () => () => {
      if (image) URL.revokeObjectURL(image.url);
    },
    [image]
  );
  if (!files.length) return null;
  const perform = async (file: DocumentSourceFile, preview = false) => {
    setBusy(true);
    setError("");
    try {
      if (preview && file.preview_url) {
        const blob = await qualityApi.blob(file.preview_url);
        setImage({ url: URL.createObjectURL(blob), name: file.name });
      } else await qualityApi.download(file.download_url, file.name);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const original = files.find((file) => file.kind === "original");
  const attachments = files.filter((file) => file.kind !== "original");
  return (
    <section className="space-y-3 rounded-md border border-subtle p-3 text-12">
      {original && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="min-w-0 font-medium break-words">原件 · {original.name}</span>
          <div className="flex gap-2">
            {original.preview_url && (
              <Button
                type="button"
                size="sm"
                variant="neutral-primary"
                disabled={busy}
                onClick={() => perform(original, true)}
              >
                查看原图
              </Button>
            )}
            <Button type="button" size="sm" variant="neutral-primary" disabled={busy} onClick={() => perform(original)}>
              下载完整原件
            </Button>
          </div>
        </div>
      )}
      <details>
        <summary className="cursor-pointer text-secondary">附件与完整性（{attachments.length}）</summary>
        <div className="mt-3 space-y-3">
          {original && <p className="break-all text-secondary">SHA256 · {original.sha256}</p>}
          {attachments.map((file) => (
            <div key={file.id} className="flex flex-wrap items-center justify-between gap-2">
              <span className="min-w-0 break-all">
                {file.name} · {(file.size / 1024).toFixed(1)} KiB
              </span>
              <div className="flex gap-2">
                {file.preview_url && (
                  <Button
                    type="button"
                    size="sm"
                    variant="neutral-primary"
                    disabled={busy}
                    onClick={() => void perform(file, true)}
                  >
                    预览图片
                  </Button>
                )}
                <Button
                  type="button"
                  size="sm"
                  variant="neutral-primary"
                  disabled={busy}
                  onClick={() => void perform(file)}
                >
                  下载
                </Button>
              </div>
            </div>
          ))}
        </div>
      </details>
      {image && (
        <div className="space-y-2">
          <img src={image.url} alt={image.name} className="max-h-64 max-w-full rounded object-contain" />
          <button type="button" className="text-accent-primary" onClick={() => setImage(undefined)}>
            关闭预览
          </button>
        </div>
      )}
      {error && (
        <p role="alert" className="text-danger-primary">
          {error}
        </p>
      )}
    </section>
  );
}
