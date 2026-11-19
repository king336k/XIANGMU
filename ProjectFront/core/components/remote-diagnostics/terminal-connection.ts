// SPDX-License-Identifier: AGPL-3.0-only
import type { TerminalSnapshot, TerminalStatus, TerminalTarget, TerminalSession } from "./types";

type RemoteApi = {
  read<T>(url: string): Promise<T>;
  write<T>(url: string, data: object): Promise<T>;
};

export function encodeTerminalInput(data: string): string {
  return btoa(Array.from(new TextEncoder().encode(data), (byte) => String.fromCharCode(byte)).join(""));
}

export function decodeTerminalOutput(data: string): Uint8Array {
  return Uint8Array.from(atob(data), (character) => character.charCodeAt(0));
}

/** One owner per PTY: ordered input, bounded buffering, and cleanup even during a slow open. */
export class TerminalConnection {
  private sessionId = "";
  private disposed = false;
  private cursor = 0;
  private outputIds = new Set<string>();
  private pollTimer: ReturnType<typeof setTimeout> | undefined;
  private inputTimer: ReturnType<typeof setTimeout> | undefined;
  private inputQueue: Uint8Array[] = [];
  private queuedBytes = 0;
  private sending = false;
  private stream: WebSocket | undefined;
  private streamSeq = 0;
  private pendingAcks = new Map<
    number,
    { resolve: () => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> }
  >();
  private resizeQueue: { cols: number; rows: number } | undefined;

  constructor(
    private api: RemoteApi,
    private base: string,
    private output: (bytes: Uint8Array) => void,
    private onStatus: (status: TerminalStatus, error?: unknown) => void,
    private onSession?: (session: TerminalSession) => void
  ) {}

  private get url() {
    return `${this.base}sessions/${encodeURIComponent(this.sessionId)}/`;
  }

  async open(
    deviceId: string,
    cols: number,
    rows: number,
    target: TerminalTarget = "operator",
    expectedRevision?: string
  ) {
    this.onStatus("connecting");
    try {
      if (target === "robot" && !expectedRevision?.trim())
        throw new Error("机器人连接信息尚未确认，请先在DAQ连接机器人。");
      const session = await this.api.write<TerminalSession>(this.base, {
        action: "open",
        device_id: deviceId,
        cols,
        rows,
        target,
        ...(expectedRevision ? { expected_target_revision: expectedRevision } : {}),
      });
      this.sessionId = session.id;
      if (this.disposed) {
        await this.closeSession();
        return;
      }
      if (session.status !== "open") throw new Error("远程终端未能建立，请重试。");
      if (
        target === "robot" &&
        (session.target !== "robot" ||
          !(session.identity || session.target_identity)?.host ||
          (expectedRevision && session.target_revision !== expectedRevision))
      ) {
        throw new Error("机器人目标身份未确认，请刷新设备状态后重试。");
      }
      this.onSession?.(session);
      this.onStatus("open");
      if (!(await this.openStream()) && !this.disposed) void this.poll();
    } catch (error) {
      if (!this.disposed) this.fail(error);
    }
  }

  input(data: string) {
    if (this.disposed || !this.sessionId) return;
    const bytes = new TextEncoder().encode(data);
    if (this.queuedBytes + bytes.length > 256 * 1024) {
      this.fail(new Error("终端输入积压过多，连接已关闭；请重新连接。"));
      return;
    }
    for (let offset = 0; offset < bytes.length; offset += 4096) {
      this.inputQueue.push(bytes.slice(offset, offset + 4096));
    }
    this.queuedBytes += bytes.length;
    if (!this.sending && !this.inputTimer) {
      this.inputTimer = setTimeout(() => {
        this.inputTimer = undefined;
        void this.flush();
      }, 30);
    }
  }

  resize(cols: number, rows: number) {
    if (this.disposed || !this.sessionId) return;
    this.resizeQueue = { cols, rows };
    void this.flush();
  }

  private async flush() {
    if (this.sending) return;
    clearTimeout(this.inputTimer);
    this.inputTimer = undefined;
    this.sending = true;
    try {
      await this.flushNext();
    } catch (error) {
      if (!this.disposed) this.fail(error);
    } finally {
      this.sending = false;
    }
  }

  private async flushNext(): Promise<void> {
    if (this.disposed) return;
    const first = this.inputQueue.shift();
    let input = first;
    if (first && this.inputQueue.length && first.length < 4096) {
      const chunks = [first];
      let size = first.length;
      while (this.inputQueue[0] && size + this.inputQueue[0].length <= 4096) {
        const next = this.inputQueue.shift()!;
        chunks.push(next);
        size += next.length;
      }
      input = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) {
        input.set(chunk, offset);
        offset += chunk.length;
      }
    }
    if (input) {
      await this.send({
        action: "input",
        data: btoa(Array.from(input, (byte) => String.fromCharCode(byte)).join("")),
      });
      this.queuedBytes -= input.length;
    } else if (this.resizeQueue) {
      const dimensions = this.resizeQueue;
      this.resizeQueue = undefined;
      await this.send({ action: "resize", ...dimensions });
    } else return;
    await this.flushNext();
  }

  private async openStream(): Promise<boolean> {
    if (typeof window === "undefined" || typeof WebSocket === "undefined") return false;
    const url = new URL(`${this.base}terminal-stream/${encodeURIComponent(this.sessionId)}/`, window.location.origin);
    if (url.origin !== window.location.origin) return false;
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    return new Promise((resolve) => {
      const socket = new WebSocket(url);
      let ready = false;
      let settled = false;
      const finish = (value: boolean) => {
        if (!settled) {
          settled = true;
          resolve(value);
        }
      };
      const timeout = setTimeout(() => {
        if (!ready) {
          socket.close();
          finish(false);
        }
      }, 1500);
      socket.addEventListener("open", () => {
        clearTimeout(timeout);
        if (this.disposed) {
          socket.close();
          finish(false);
          return;
        }
        ready = true;
        this.stream = socket;
        finish(true);
      });
      socket.addEventListener("message", (event) => {
        if (this.disposed) return;
        try {
          const message = JSON.parse(event.data);
          if (message.type === "ack") {
            const pending = this.pendingAcks.get(message.seq);
            if (pending) {
              clearTimeout(pending.timer);
              this.pendingAcks.delete(message.seq);
              pending.resolve();
            }
          } else if (message.type === "fast_output") {
            for (const chunk of message.events) this.writeOutput(chunk.data, chunk.source_id);
          } else if (message.type === "output") this.consume(message);
          else if (message.type === "error") this.fail(new Error(message.error || "终端连接已中断，请重新连接。"));
        } catch {
          this.fail(new Error("终端返回了无效数据，请重新连接。"));
        }
      });
      socket.addEventListener("error", () => {
        if (!ready) {
          clearTimeout(timeout);
          socket.close();
          finish(false);
        }
      });
      socket.addEventListener("close", () => {
        clearTimeout(timeout);
        if (!ready) finish(false);
        else if (!this.disposed) this.fail(new Error("终端实时连接已断开，请重新连接。"));
      });
    });
  }

  private async send(payload: object): Promise<unknown> {
    if (!this.stream) return this.api.write(this.url, payload);
    const socket = this.stream;
    if (socket.readyState !== WebSocket.OPEN || socket.bufferedAmount > 256 * 1024)
      throw new Error("终端连接积压或已断开，请重新连接。");
    const seq = ++this.streamSeq;
    return new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendingAcks.delete(seq);
        reject(new Error("终端输入确认超时，请重新连接。"));
      }, 10000);
      this.pendingAcks.set(seq, { resolve, reject, timer });
      try {
        socket.send(JSON.stringify({ ...payload, seq }));
      } catch (error) {
        clearTimeout(timer);
        this.pendingAcks.delete(seq);
        reject(error);
      }
    });
  }

  private writeOutput(data: string, sourceId?: string) {
    if (sourceId && this.outputIds.has(sourceId)) return;
    if (sourceId) {
      this.outputIds.add(sourceId);
      if (this.outputIds.size > 1024) this.outputIds.delete(this.outputIds.values().next().value!);
    }
    this.output(decodeTerminalOutput(data));
  }

  private consume(response: TerminalSnapshot) {
    if (this.disposed) return;
    this.onSession?.(response);
    for (const event of response.events) {
      if (event.seq > this.cursor) {
        this.writeOutput(event.data, event.source_id);
        this.cursor = event.seq;
      }
    }
    this.cursor = Math.max(this.cursor, response.cursor);
    if (response.status !== "open") {
      this.onStatus(
        response.status === "closed" && !response.error ? "closed" : "error",
        response.error ? new Error(response.error) : undefined
      );
      this.dispose();
    }
  }

  private async poll() {
    try {
      const response = await this.api.read<TerminalSnapshot>(`${this.url}?after=${this.cursor}`);
      this.consume(response);
      if (this.disposed) return;
      this.pollTimer = setTimeout(() => void this.poll(), 400);
    } catch (error) {
      if (!this.disposed) this.fail(error);
    }
  }

  private fail(error: unknown) {
    this.onStatus("error", error);
    this.dispose();
  }

  private async closeSession() {
    if (!this.sessionId) return;
    await this.api.write(this.url, { action: "close" }).catch(() => undefined);
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    this.stream?.close();
    for (const pending of this.pendingAcks.values()) {
      clearTimeout(pending.timer);
      pending.reject(new Error("终端已关闭。"));
    }
    this.pendingAcks.clear();
    clearTimeout(this.pollTimer);
    clearTimeout(this.inputTimer);
    this.inputQueue = [];
    this.resizeQueue = undefined;
    void this.closeSession();
  }
}
