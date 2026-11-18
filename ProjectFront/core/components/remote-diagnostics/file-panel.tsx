// SPDX-License-Identifier: AGPL-3.0-only
import { useEffect, useRef, useState } from "react";
import { Download, Upload, Folder, FileText, ArrowUp, RefreshCw } from "lucide-react";
import { qualityApi, errorMessage } from "@/components/quality/api";
import { remoteDiagnosticsBase } from "./types";
import type { RemoteDevice } from "./types";
import { Modal } from "@/components/quality/shared";
import { FeedbackPicker } from "./feedback-picker";
import type { FeedbackChoice } from "./feedback-picker";

type Entry = { name: string; kind: "file" | "directory"; size: number; modified: number };
type Listing = { username?: string; root: string; path: string; entries: Entry[]; offset: number; total: number };
type Prepared = { ticket: string; filename: string; size: number; sha256: string; skipped: number };
const delay = () => new Promise((resolve) => setTimeout(resolve, 350));
const sizeText = (size: number) =>
  size < 1024 ? `${size} B` : size < 1048576 ? `${(size / 1024).toFixed(1)} KB` : `${(size / 1048576).toFixed(1)} MB`;

export function FilePanel({ device }: { device: RemoteDevice }) {
  const [target, setTarget] = useState("operator");
  const configuredRobot = device.capabilities.robot as { username?: string; host?: string } | undefined;
  const [robotUsername, setRobotUsername] = useState(configuredRobot?.username || "");
  const [path, setPath] = useState("");
  const [listing, setListing] = useState<Listing>();
  const [selected, setSelected] = useState<Entry>();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [localFile, setLocalFile] = useState<File>();
  const [uploadFeedback, setUploadFeedback] = useState<FeedbackChoice>();
  const uploadDefectId = uploadFeedback?.id || "";
  const [uploadName, setUploadName] = useState("");
  const [uploadDialog, setUploadDialog] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const generation = useRef(0);
  useEffect(
    () => () => {
      generation.current++;
    },
    []
  );

  async function request<T>(payload: object, current: number): Promise<T> {
    const job = await qualityApi.write<{ id: string }>(`${remoteDiagnosticsBase}files/`, {
      device_id: device.id,
      target,
      ...payload,
    });
    const deadline = Date.now() + 120000;
    async function poll(): Promise<T> {
      if (Date.now() >= deadline) throw new Error("文件操作超时，请检查现场连接。");
      if (current !== generation.current) throw new Error("文件操作已取消。");
      const status = await qualityApi.read<{ status: string; error: string; result: T }>(
        `${remoteDiagnosticsBase}files/${job.id}/`
      );
      if (status.status === "done") {
        if (status.error) throw new Error(status.error);
        return status.result;
      }
      if (status.status === "expired") throw new Error("文件请求已过期，请重试。");
      await delay();
      return poll();
    }
    return poll();
  }
  async function browse(next: string, offset = 0) {
    const current = ++generation.current;
    setBusy(true);
    setError("");
    setMessage("");
    setSelected(undefined);
    try {
      const result = await request<Listing>({ action: "list", path: next, offset }, current);
      if (current === generation.current) {
        if (target === "robot" && result.username) setRobotUsername(result.username);
        setListing(result);
        setPath(result.path === "." ? "" : result.path);
      }
    } catch (cause) {
      if (current === generation.current) {
        setError(errorMessage(cause));
        setMessage("");
      }
    } finally {
      if (current === generation.current) setBusy(false);
    }
  }
  async function download() {
    const current = ++generation.current;
    setBusy(true);
    setError("");
    setMessage("正在准备下载…");
    try {
      const remotePath = selected ? [path, selected.name].filter(Boolean).join("/") : path;
      const prepared = await request<Prepared>({ action: "prepare", path: remotePath }, current);
      if (!Number.isSafeInteger(prepared.size) || prepared.size < 0 || prepared.size > 256 * 1024 * 1024)
        throw new Error("文件超过本次下载大小限制。");
      const chunks: Uint8Array<ArrayBuffer>[] = [];
      async function receiveChunk(offset: number): Promise<void> {
        if (offset >= prepared.size) return;
        const part = await request<{ data: string; offset: number; next_offset: number }>(
          { action: "chunk", ticket: prepared.ticket, offset },
          current
        );
        const raw = Uint8Array.from(atob(part.data), (c) => c.charCodeAt(0));
        if (
          part.offset !== offset ||
          raw.length === 0 ||
          part.next_offset !== offset + raw.length ||
          part.next_offset > prepared.size
        )
          throw new Error("文件分块校验失败，请重试。");
        chunks.push(raw);
        setMessage(`正在下载 ${prepared.filename} · ${Math.round((part.next_offset / prepared.size) * 100)}%`);
        return receiveChunk(part.next_offset);
      }
      await receiveChunk(0);
      const blob = new Blob(chunks);
      // HTTP test environments lack SubtleCrypto; verify with the already installed SHA256 library.
      const { sha256 } = await import("@noble/hashes/sha256");
      const digest = Array.from(sha256(new Uint8Array(await blob.arrayBuffer())), (b) =>
        b.toString(16).padStart(2, "0")
      ).join("");
      if (digest !== prepared.sha256) throw new Error("文件完整性校验失败，未保存下载。");
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = prepared.filename;
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
      setMessage(
        `已校验并下载 ${prepared.filename}${prepared.skipped ? `；已跳过 ${prepared.skipped} 个密钥、链接或不可下载项` : ""}`
      );
    } catch (cause) {
      if (current === generation.current) setError(errorMessage(cause));
    } finally {
      if (current === generation.current) setBusy(false);
    }
  }
  async function upload() {
    if (!localFile || !listing) return;
    if (
      !uploadName.trim() ||
      /[/\\]/.test(uploadName) ||
      uploadName.includes("\0") ||
      [".", ".."].includes(uploadName.trim())
    ) {
      setError("请填写不含路径分隔符的目标文件名。");
      return;
    }
    const current = ++generation.current;
    setBusy(true);
    setError("");
    setMessage("正在校验本机文件…");
    let ticket = "";
    try {
      if (localFile.size > 256 * 1024 * 1024) throw new Error("单个文件最多 256 MB。");
      const { sha256 } = await import("@noble/hashes/sha256");
      const digest = Array.from(sha256(new Uint8Array(await localFile.arrayBuffer())), (b) =>
        b.toString(16).padStart(2, "0")
      ).join("");
      const started = await request<{ ticket: string }>(
        {
          action: "upload_start",
          path,
          filename: uploadName.trim(),
          size: localFile.size,
          sha256: digest,
          ...(uploadDefectId ? { defect_id: uploadDefectId } : {}),
        },
        current
      );
      ticket = started.ticket;
      const sourceFile = localFile;
      async function sendChunk(offset: number): Promise<void> {
        if (offset >= sourceFile.size) return;
        const bytes = new Uint8Array(await sourceFile.slice(offset, offset + 96 * 1024).arrayBuffer());
        let raw = "";
        for (let i = 0; i < bytes.length; i += 8192) raw += String.fromCharCode(...bytes.subarray(i, i + 8192));
        const result = await request<{ next_offset: number }>(
          { action: "upload_chunk", ticket, offset, data: btoa(raw) },
          current
        );
        if (result.next_offset !== offset + bytes.length) throw new Error("上传分块校验失败。");
        setMessage(`正在上传 ${uploadName.trim()} · ${Math.round((result.next_offset / sourceFile.size) * 100)}%`);
        return sendChunk(result.next_offset);
      }
      await sendChunk(0);
      const result = await request<{ uploaded: boolean; path: string; sha256: string }>(
        { action: "upload_finish", ticket },
        current
      );
      if (result.uploaded !== true || result.sha256 !== digest) throw new Error("远端文件完整性校验失败。");
      setMessage(`已上传并校验：${result.path}`);
      setLocalFile(undefined);
      setUploadDialog(false);
      try {
        const updated = await request<Listing>({ action: "list", path }, current);
        setListing(updated);
      } catch (cause) {
        setError(`文件已上传，但目录刷新失败：${errorMessage(cause)}`);
      }
      setSelected(undefined);
    } catch (cause) {
      if (current === generation.current) {
        setError(errorMessage(cause));
        setMessage("");
      }
      if (ticket) void request({ action: "upload_abort", ticket }, current).catch(() => {});
    } finally {
      if (current === generation.current) setBusy(false);
    }
  }
  const enabled = device.online && device.can_connect;
  return (
    <section aria-label="现场文件" className="space-y-3 rounded border border-subtle p-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-14 font-medium">现场文件</h2>
          <p className="mt-1 text-12 text-secondary">
            浏览操作电脑或经由它连接的机器人；文件夹打包为 tar.gz 下载到本机。
          </p>
        </div>
        <select
          aria-label="文件位置"
          value={target}
          disabled={busy}
          onChange={(e) => {
            generation.current++;
            setTarget(e.target.value);
            setListing(undefined);
            setSelected(undefined);
            setPath("");
            setError("");
            setMessage("");
          }}
          className="rounded border border-subtle bg-surface-1 px-3 py-2 text-13"
        >
          <option value="operator">操作电脑：{device.username}</option>
          <option value="robot">机器人：{robotUsername || "用户名待确认"}</option>
        </select>
      </header>
      <input
        ref={fileInput}
        type="file"
        className="hidden"
        aria-label="选择本机文件或压缩包"
        disabled={busy}
        onChange={(event) => {
          const file = event.target.files?.[0];
          setLocalFile(file);
          event.currentTarget.value = "";
          setUploadName(file?.name || "");
          if (file && listing) setUploadDialog(true);
        }}
      />
      <div className="flex flex-wrap items-center gap-2" aria-label="文件操作">
        <button
          type="button"
          disabled={busy || !enabled}
          onClick={() => fileInput.current?.click()}
          className="inline-flex items-center gap-1.5 rounded border border-subtle px-3 py-2 text-13 disabled:opacity-40"
        >
          <Upload className="size-3.5" />
          上传
        </button>
        <button
          type="button"
          disabled={busy || !enabled || !listing}
          onClick={() => void download()}
          className="inline-flex items-center gap-1.5 rounded border border-subtle px-3 py-2 text-13 disabled:opacity-40"
        >
          <Download className="size-3.5" />
          {selected ? "下载所选" : "下载当前目录"}
        </button>
        <button
          type="button"
          disabled={busy || !enabled}
          onClick={() => void browse(path)}
          className="inline-flex items-center gap-1.5 rounded border border-subtle px-3 py-2 text-13 disabled:opacity-40"
        >
          <RefreshCw className="size-3.5" />
          {listing ? "刷新" : "浏览文件"}
        </button>
      </div>
      <div className="flex min-w-0 items-center gap-2 border-y border-subtle py-2">
        <button
          type="button"
          disabled={busy || !enabled || !path}
          onClick={() => void browse(path.split("/").slice(0, -1).join("/"))}
          className="rounded p-1.5 disabled:opacity-40"
          aria-label="上一级目录"
        >
          <ArrowUp className="size-4" />
        </button>
        <p className="font-mono min-w-0 flex-1 text-12 break-all text-secondary">
          {listing ? `${listing.root}/${path}` : "请选择目标并浏览目录"}
        </p>
      </div>
      {localFile && !uploadDialog && (
        <div className="flex flex-wrap items-center gap-2 text-12">
          <span className="min-w-0 flex-1 truncate">已选本机文件：{localFile.name}</span>
          <button
            type="button"
            disabled={!listing || busy}
            onClick={() => setUploadDialog(true)}
            className="text-accent-primary"
          >
            {listing ? "确认上传位置" : "请先浏览目标目录"}
          </button>
          <button type="button" disabled={busy} onClick={() => setLocalFile(undefined)} className="text-secondary">
            取消
          </button>
        </div>
      )}
      {uploadDialog && localFile && (
        <Modal
          title="确认上传"
          width="compact"
          onClose={() => {
            if (!busy) setUploadDialog(false);
          }}
        >
          <div className="space-y-4">
            <p className="text-13">
              {localFile.name} · {sizeText(localFile.size)}
            </p>
            <label className="block text-12">
              目标文件名
              <input
                aria-label="目标文件名"
                value={uploadName}
                onChange={(event) => setUploadName(event.target.value)}
                maxLength={255}
                disabled={busy}
                className="mt-1 block w-full rounded border border-subtle bg-surface-1 px-3 py-2"
              />
            </label>
            <p className="text-12 break-all text-secondary">
              目标：{target === "robot" ? `机器人：${robotUsername || "用户名待确认"}` : `操作电脑：${device.username}`}
              <br />
              {listing ? `${listing.root}/${path}/${uploadName.trim()}`.replace(/\/{2,}/g, "/") : "请先选择目标目录"}
            </p>
            <div>
              <p className="mb-2 text-12">关联反馈（可选）</p>
              <FeedbackPicker
                device={device}
                value={uploadFeedback}
                onChange={setUploadFeedback}
                optional
                disabled={busy}
              />
            </div>
            <p className="text-11 text-secondary">最多 256 MB · 不覆盖同名文件 · 不自动解压或执行</p>
            <button
              type="button"
              disabled={busy || !enabled || !listing || !uploadName.trim()}
              onClick={() => void upload()}
              className="rounded bg-accent-primary px-3 py-2 text-13 text-on-color disabled:opacity-40"
            >
              确认上传到当前目录
            </button>
            {busy && (
              <p role="status" className="text-12 text-secondary">
                {message}
              </p>
            )}
            {error && (
              <p role="alert" className="text-12 text-danger-primary">
                {error}
              </p>
            )}
          </div>
        </Modal>
      )}
      {listing && (
        <div className="max-h-80 overflow-auto rounded border border-subtle">
          <table className="w-full text-left text-13">
            <thead className="sticky top-0 bg-surface-2 text-12 text-secondary">
              <tr>
                <th className="px-3 py-2">名称</th>
                <th className="px-3 py-2">大小</th>
                <th className="px-3 py-2">修改时间</th>
              </tr>
            </thead>
            <tbody>
              {listing.entries.map((entry) => (
                <tr
                  key={entry.name}
                  onClick={() => setSelected(entry)}
                  onDoubleClick={() => {
                    if (entry.kind === "directory" && !busy) void browse([path, entry.name].filter(Boolean).join("/"));
                  }}
                  className={selected?.name === entry.name ? "bg-accent-subtle" : "hover:bg-surface-2"}
                >
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => setSelected(entry)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" && entry.kind === "directory") {
                          event.preventDefault();
                          void browse([path, entry.name].filter(Boolean).join("/"));
                        }
                      }}
                      className="inline-flex max-w-full items-center gap-2 text-left break-all"
                    >
                      {entry.kind === "directory" ? (
                        <Folder className="size-4 shrink-0 text-accent-primary" />
                      ) : (
                        <FileText className="size-4 shrink-0 text-secondary" />
                      )}
                      {entry.name}
                    </button>
                    {entry.kind === "directory" && (
                      <button
                        disabled={busy}
                        onClick={(event) => {
                          event.stopPropagation();
                          void browse([path, entry.name].filter(Boolean).join("/"));
                        }}
                        className="ml-3 text-12 text-accent-primary"
                      >
                        打开
                      </button>
                    )}
                  </td>
                  <td className="px-3 py-2 text-12 text-secondary">
                    {entry.kind === "directory" ? "—" : sizeText(entry.size)}
                  </td>
                  <td className="px-3 py-2 text-12 text-secondary">
                    {new Date(entry.modified * 1000).toLocaleString("zh-CN", { hour12: false })}
                  </td>
                </tr>
              ))}
              {!listing.entries.length && (
                <tr>
                  <td colSpan={3} className="px-3 py-6 text-center text-secondary">
                    此目录为空。
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {listing && listing.total > 100 && (
        <div className="flex items-center gap-3 text-12">
          <button
            disabled={busy || listing.offset === 0}
            onClick={() => void browse(path, Math.max(0, listing.offset - 100))}
          >
            上一页
          </button>
          <span>
            {listing.offset + 1}–{Math.min(listing.offset + 100, listing.total)} / {listing.total}
          </span>
          <button
            disabled={busy || listing.offset + 100 >= listing.total}
            onClick={() => void browse(path, listing.offset + 100)}
          >
            下一页
          </button>
        </div>
      )}
      {busy && (
        <p role="status" className="text-12 text-secondary">
          {message || "正在读取现场文件…"}
        </p>
      )}
      {!busy && message && (
        <p role="status" className="text-12 text-success-primary">
          {message}
        </p>
      )}
      {error && (
        <p role="alert" className="text-13 text-danger-primary">
          {error}
        </p>
      )}
      <p className="text-11 text-tertiary">
        单次传输最多 256 MB；同名文件不覆盖，可修改目标文件名后重试。压缩包不自动解压或执行。
      </p>
    </section>
  );
}
