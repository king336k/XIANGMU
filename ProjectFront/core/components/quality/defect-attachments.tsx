import { renderNumericDateTime } from "@plane/utils";
// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useState } from "react";
import useSWR from "swr";
import { Paperclip, FileText, Image as ImageIcon, Download } from "lucide-react";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage, attachmentDisplayName } from "./api";
import { AttachmentViewer } from "./attachment-viewer";
import { useDropzone } from "react-dropzone";
import { InlineFilePreview } from "./inline-file-preview";
import { can } from "./types";
import type { Context } from "./types";

type FileRecord = {
  id: string;
  name: string;
  size: number;
  source_system: string;
  sha256: string;
  uploader: string;
  created_at: string;
};
export async function uploadDefectFiles(base: string, defectId: string, files: File[]) {
  return files.reduce<Promise<void>>(
    (previous, file) =>
      previous.then(async () => {
        if (file.size > 20 * 1024 * 1024) throw new Error(`${file.name} 超过20MB，请压缩或拆分后上传。`);
        const form = new FormData();
        form.append("file", file);
        await qualityApi.write(`${base}defects/${defectId}/attachments/`, form);
        return undefined;
      }),
    Promise.resolve()
  );
}

export function DefectAttachments({ base, defectId, context }: { base: string; defectId: string; context: Context }) {
  const { data, error, mutate } = useSWR(`${base}defects/${defectId}/attachments/`, (url: string) =>
    qualityApi.read<FileRecord[]>(url)
  );
  const [busy, setBusy] = useState(false),
    [actionError, setActionError] = useState("");
  const [preview, setPreview] = useState<{ id: string; name: string; image?: string; text?: string }>();
  useEffect(
    () => () => {
      if (preview?.image) URL.revokeObjectURL(preview.image);
    },
    [preview]
  );
  const perform = async (action: () => Promise<void>) => {
    setBusy(true);
    setActionError("");
    try {
      await action();
    } catch (e) {
      setActionError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    noClick: true,
    multiple: true,
    maxSize: 20 * 1024 * 1024,
    maxFiles: 10,
    disabled: busy || !can(context, "package"),
    onDrop: (files, rejected) => {
      if (rejected.length) {
        setActionError("部分文件超过20MB或单次超过10个，请调整后重试。");
        return;
      }
      void perform(async () => {
        await uploadDefectFiles(base, defectId, files);
        await mutate();
      });
    },
  });
  return (
    <section className="space-y-4 rounded-md border border-subtle p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Paperclip className="size-4" />
          <h3 className="text-13 font-medium">附件与日志文件 {data ? `（${data.length}）` : ""}</h3>
        </div>
        {!!data?.length && (
          <Button
            type="button"
            variant="neutral-primary"
            size="sm"
            aria-label="一键打包下载"
            disabled={busy}
            onClick={() =>
              void perform(() =>
                qualityApi.download(
                  `${base}defects/${encodeURIComponent(defectId)}/attachments/download/`,
                  `${defectId.replace(/[^a-zA-Z0-9_-]/g, "_")}-附件.zip`
                )
              )
            }
          >
            <Download className="mr-1 size-3.5" />
            一键打包下载
          </Button>
        )}
      </div>
      {!data && !error && (
        <p role="status" className="text-12 text-secondary">
          正在读取附件…
        </p>
      )}
      {data?.length === 0 && <p className="text-13 text-secondary">暂无附件，可添加截图、日志或诊断包。</p>}
      {can(context, "package") && (
        <details open={data?.length === 0} className="text-12 text-secondary">
          <summary className="w-fit cursor-pointer">添加附件</summary>
          <div
            {...getRootProps()}
            className={`rounded-md border border-dashed p-4 text-center text-12 ${isDragActive ? "border-accent-primary bg-layer-1" : "border-subtle text-secondary"}`}
          >
            <input {...getInputProps()} aria-label="选择附件" />
            <p>{isDragActive ? "放下文件即可上传" : "拖拽图片、日志或文件到这里"}</p>
            <Button type="button" variant="neutral-primary" className="mt-2" disabled={busy} onClick={open}>
              选择文件
            </Button>
            <p className="mt-2">支持多选 · 单文件20MB以内</p>
          </div>
        </details>
      )}
      {data?.map((file, index) => {
        const displayName = attachmentDisplayName(file.name);
        const image = /\.(png|jpe?g|gif|webp)$/i.test(file.name);
        const readable = image || /\.(log|txt|json|csv|md|ya?ml)$/i.test(file.name);
        return (
          <article key={file.id} className="overflow-hidden rounded-md border border-subtle">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-subtle bg-layer-1 px-3 py-2.5">
              <div className="flex min-w-0 flex-1 items-start gap-2">
                {image ? (
                  <ImageIcon className="mt-0.5 size-4 shrink-0" />
                ) : (
                  <FileText className="mt-0.5 size-4 shrink-0" />
                )}
                <div className="min-w-0">
                  <p className="text-13 font-medium break-all">{displayName}</p>
                  <p className="mt-1 text-11 text-secondary">
                    {file.size.toLocaleString()} 字节 ·{" "}
                    {file.source_system === "ENGRAM_DAQ" || file.source_system === "daq" ? "DAQ 上报" : "手工添加"} ·
                    {file.uploader || "成员"} · {file.created_at ? renderNumericDateTime(file.created_at) : ""} ·
                    文件已校验
                  </p>
                </div>
              </div>
              <div className="flex gap-2">
                {readable && (
                  <button
                    type="button"
                    className="rounded px-2 py-1 text-12 whitespace-nowrap text-secondary hover:bg-surface-1 hover:text-primary disabled:opacity-50"
                    disabled={busy}
                    onClick={() =>
                      void perform(async () => {
                        const blob = await qualityApi.blob(`${base}files/${file.id}/preview/`);
                        if (image) setPreview({ id: file.id, name: displayName, image: URL.createObjectURL(blob) });
                        else setPreview({ id: file.id, name: displayName, text: await blob.text() });
                      })
                    }
                  >
                    {image ? "预览图片" : "展开阅读"}
                  </button>
                )}
                <button
                  type="button"
                  aria-label={`下载 ${displayName}`}
                  title="下载原文件"
                  className="rounded p-1.5 text-secondary hover:bg-surface-1 hover:text-primary disabled:opacity-50"
                  disabled={busy}
                  onClick={() =>
                    void perform(async () => {
                      await qualityApi.download(
                        `${base}files/${file.id}/download/`,
                        displayName.split("/").pop() || displayName
                      );
                    })
                  }
                >
                  <Download className="size-4" />
                </button>
              </div>
            </div>
            {index < 3 && (
              <div className="px-3 pb-3">
                <InlineFilePreview
                  base={base}
                  file={file}
                  onOpen={() =>
                    void perform(async () => {
                      const blob = await qualityApi.blob(`${base}files/${file.id}/preview/`);
                      setPreview({ id: file.id, name: displayName, image: URL.createObjectURL(blob) });
                    })
                  }
                />
              </div>
            )}
          </article>
        );
      })}
      {busy && (
        <p role="status" className="text-12 text-secondary">
          正在处理文件…
        </p>
      )}
      {(error || actionError) && (
        <p role="alert" className="text-13 text-danger-primary">
          {actionError || errorMessage(error)}
        </p>
      )}
      {preview && <AttachmentViewer base={base} preview={preview} onClose={() => setPreview(undefined)} />}
    </section>
  );
}
