import { useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "../quality/api";
type Status = {
  enabled: boolean;
  configured: boolean;
  model: string;
  status: string;
  indexed_count: number;
  eligible_count: number;
  can_build: boolean;
  error_code?: string;
};
const names: Record<string, string> = {
  disabled: "未启用",
  unconfigured: "未配置向量模型",
  idle: "尚未建立",
  queued: "排队中",
  running: "正在建立",
  completed: "已建立",
  failed: "建立失败",
};
export function SemanticIndexPanel({ base }: { base: string }) {
  const { data, error, mutate } = useSWR(`${base}semantic-index/`, (url: string) => qualityApi.read<Status>(url), {
    refreshInterval: 5000,
  });
  const [busy, setBusy] = useState(false),
    [failure, setFailure] = useState("");
  if (!data?.enabled && !error) return null;
  return (
    <section className="space-y-3 rounded-md border border-subtle p-4" aria-label="语义检索索引">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-14 font-medium">语义检索索引</h3>
        <span className="text-12 text-secondary">{names[data?.status || ""] || "状态读取中"}</span>
      </div>
      {data && (
        <p className="text-12 text-secondary">
          已索引 {data.indexed_count} / {data.eligible_count} 条有效发布知识{data.model ? ` · ${data.model}` : ""}
        </p>
      )}
      {(error || failure) && (
        <p role="alert" className="text-12 text-danger-primary">
          {failure || errorMessage(error)}
        </p>
      )}
      {data?.can_build && (
        <>
          <p className="text-12 text-secondary">建立索引会将本项目已发布知识发送到已配置的向量模型接口；草稿不参与。</p>
          <Button
            variant="neutral-primary"
            disabled={busy || !data.configured || ["queued", "running"].includes(data.status)}
            onClick={async () => {
              setBusy(true);
              setFailure("");
              try {
                await qualityApi.write(`${base}semantic-index/`, { action: "build" });
                await mutate();
              } catch (e) {
                setFailure(errorMessage(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "正在提交…" : data.indexed_count ? "更新索引" : "建立索引"}
          </Button>
        </>
      )}
    </section>
  );
}
