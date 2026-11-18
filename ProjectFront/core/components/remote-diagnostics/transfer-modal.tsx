// SPDX-License-Identifier: AGPL-3.0-only
import type { ReactNode } from "react";
import { ArrowLeft, ArrowRight, FileText, FolderOpen, Upload } from "lucide-react";
import { Modal } from "@/components/quality/shared";

export type TransferDirection = "upload" | "download";
export function TransferModal({
  direction,
  onDirection,
  targetControl,
  remoteBrowser,
  remoteLabel,
  localFile,
  remoteName,
  remotePath,
  uploadName,
  onUploadName,
  onPickLocal,
  advanced,
  busy,
  enabled,
  message,
  error,
  onStart,
  onClose,
}: {
  direction: TransferDirection;
  onDirection: (value: TransferDirection) => void;
  targetControl: ReactNode;
  remoteBrowser: ReactNode;
  remoteLabel?: string;
  localFile?: File;
  remoteName: string;
  remotePath: string;
  uploadName: string;
  onUploadName: (value: string) => void;
  onPickLocal: () => void;
  advanced: ReactNode;
  busy: boolean;
  enabled: boolean;
  message: string;
  error: string;
  onStart: () => void;
  onClose: () => void;
}) {
  const progress = message.match(/(\d+)%/);
  const localName = localFile ? `${localFile.name} · ${(localFile.size / 1024).toFixed(1)} KB` : "未选择本机文件";
  return (
    <Modal title="文件传输" width="wide" onClose={onClose}>
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3 text-12">
          <span className="text-secondary">本机 ⇄ 现场</span>
          {targetControl}
        </div>
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_3rem_minmax(0,1fr)]">
          <section aria-label="本机文件" className="min-w-0 rounded border border-subtle">
            <header className="border-b border-subtle bg-surface-2 px-3 py-2 text-13 font-medium">
              本机（当前浏览器所在电脑）
            </header>
            <div className="min-h-64 space-y-4 p-3">
              {direction === "upload" ? (
                <>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={onPickLocal}
                    className="inline-flex items-center gap-2 rounded border border-subtle px-3 py-2 text-12"
                  >
                    <Upload className="size-4" />
                    选择本机文件
                  </button>
                  <div className="flex items-start gap-2 rounded bg-surface-2 p-3 text-12">
                    <FileText className="mt-0.5 size-4 shrink-0 text-secondary" />
                    <p className="min-w-0 break-all">{localName}</p>
                  </div>
                  <label className="block text-12 text-secondary">
                    远端保存文件名
                    <input
                      aria-label="目标文件名"
                      value={uploadName}
                      onChange={(event) => onUploadName(event.target.value)}
                      maxLength={255}
                      disabled={busy || !localFile}
                      className="mt-1 w-full rounded border border-subtle bg-surface-1 px-3 py-2 text-primary"
                    />
                  </label>
                </>
              ) : (
                <>
                  <div className="flex items-start gap-2 rounded bg-surface-2 p-3">
                    <FolderOpen className="size-5 shrink-0 text-secondary" />
                    <div>
                      <h3 className="text-13">浏览器下载目录</h3>
                      <p className="mt-2 text-12 leading-5 text-secondary">
                        下载保存到浏览器配置的目录；若浏览器询问，请选择本机保存位置。
                      </p>
                    </div>
                  </div>
                  <p className="text-12 text-secondary">待接收：{remoteName || "请在右侧选择文件或目录"}</p>
                </>
              )}
            </div>
          </section>
          <div aria-label="传输方向" className="flex items-center justify-center gap-2 md:flex-col">
            <button
              type="button"
              aria-label="上传到远端"
              aria-pressed={direction === "upload"}
              disabled={busy}
              onClick={() => onDirection("upload")}
              className={`rounded border p-2 ${direction === "upload" ? "border-accent-strong bg-accent-subtle text-accent-primary" : "border-subtle text-secondary"}`}
            >
              <ArrowRight className="size-5" />
            </button>
            <button
              type="button"
              aria-label="下载到本机"
              aria-pressed={direction === "download"}
              disabled={busy}
              onClick={() => onDirection("download")}
              className={`rounded border p-2 ${direction === "download" ? "border-accent-strong bg-accent-subtle text-accent-primary" : "border-subtle text-secondary"}`}
            >
              <ArrowLeft className="size-5" />
            </button>
          </div>
          <section aria-label="远端文件" className="min-w-0 rounded border border-subtle">
            <header className="border-b border-subtle bg-surface-2 px-3 py-2 text-13 font-medium">
              远端：{remoteLabel || "目标待选择"}
            </header>
            <div className="min-h-64 space-y-2 p-3">{remoteBrowser}</div>
          </section>
        </div>
        {direction === "upload" && (
          <details className="text-12">
            <summary className="cursor-pointer text-secondary">高级：关联原始反馈</summary>
            <div className="mt-3">{advanced}</div>
          </details>
        )}
        <footer className="space-y-3 border-t border-subtle pt-4">
          <p className="text-12 break-all" aria-label="传输路径">
            {direction === "upload"
              ? `${localFile?.name || "未选择本机文件"} → ${remotePath}`
              : `${remotePath} → 浏览器下载目录`}
          </p>
          {message && (
            <div role="status" className={`space-y-2 text-12 ${busy ? "text-secondary" : "text-success-primary"}`}>
              <p>{message}</p>
              {progress && (
                <progress
                  aria-label="传输进度"
                  value={Number(progress[1])}
                  max={100}
                  className="h-1.5 w-full accent-[var(--accent-primary)]"
                />
              )}
            </div>
          )}
          {error && (
            <p role="alert" className="text-12 text-danger-primary">
              {error}
            </p>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-11 text-tertiary">最多 256 MB · 不覆盖同名文件 · 不自动解压或执行</p>
            <button
              type="button"
              disabled={busy || !enabled}
              onClick={onStart}
              className="rounded bg-accent-primary px-4 py-2 text-13 text-on-color disabled:opacity-40"
            >
              {busy ? "处理中…" : "开始传输"}
            </button>
          </div>
        </footer>
      </div>
    </Modal>
  );
}
