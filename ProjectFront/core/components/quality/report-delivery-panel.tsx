import { useCollectionPagination } from "./use-collection-pagination";
// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass, Modal, Paging } from "./shared";
type Target = {
  id: string;
  name: string;
  source_instance: string;
  chat_id: string;
  enabled: boolean;
  edit_version: number;
};
type Delivery = {
  id: string;
  target_name: string;
  chat_id: string;
  text: string;
  status: string;
  attempts: number;
  last_error: string;
  sent_at: string | null;
};
const states: Record<string, string> = {
  preview: "待确认预览",
  sent: "飞书已确认接收",
  unconfirmed: "尚未确认投递，请核对",
};

export function NotificationTargetsPanel({ base }: { base: string }) {
  const { data, error, mutate } = useSWR(`${base}notification-targets/all`, () =>
    qualityApi.all<Target>(`${base}notification-targets/`)
  );
  const pagination = useCollectionPagination(`${base}:notification-targets`, data);
  const [editing, setEditing] = useState<Target | null | undefined>();
  return (
    <section className="space-y-3 border-t border-subtle pt-5">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-14 font-medium">报告投递目标</h3>
        <Button variant="neutral-primary" onClick={() => setEditing(null)}>
          登记飞书接收群
        </Button>
      </div>
      <p className="text-12 text-secondary">
        目标只登记接收群。发送前须在报告详情预览内容并确认，登记或修改目标不会发送消息。飞书连接与消息权限由管理员配置。
      </p>
      {error && (
        <p role="alert" className="text-12 text-danger-primary">
          {errorMessage(error)}
        </p>
      )}
      {!data?.length && <p className="text-12 text-secondary">尚未登记接收群。</p>}
      {pagination.rows.map((row) => (
        <div key={row.id} className="flex items-center justify-between gap-3 rounded border border-subtle p-3 text-12">
          <div>
            <p>
              {row.name} · {row.enabled ? "已启用" : "已停用"}
            </p>
            <p className="mt-1 text-secondary">
              {row.source_instance} · {row.chat_id}
            </p>
          </div>
          <Button variant="neutral-primary" onClick={() => setEditing(row)}>
            调整目标
          </Button>
        </div>
      ))}
      {data && <Paging {...pagination.paging} />}
      {editing !== undefined && (
        <Modal
          title="飞书报告接收群"
          onClose={() => setEditing(undefined)}
          onSubmit={async (form) => {
            await qualityApi.write(
              `${base}notification-targets/${editing ? editing.id + "/" : ""}`,
              {
                name: form.get("name"),
                source_instance: form.get("source_instance"),
                chat_id: form.get("chat_id"),
                enabled: form.get("enabled") === "on",
                ...(editing ? { expected_version: editing.edit_version } : {}),
              },
              editing ? "patch" : "post"
            );
            await mutate();
          }}
        >
          <Field label="目标名称 *">
            <input required name="name" maxLength={120} defaultValue={editing?.name} className={fieldClass} />
          </Field>
          <Field label="已配置的飞书连接实例 *">
            <input
              required
              name="source_instance"
              pattern="[a-zA-Z0-9_-]{1,80}"
              maxLength={80}
              defaultValue={editing?.source_instance}
              className={fieldClass}
            />
          </Field>
          <Field label="飞书群chat_id *">
            <input
              required
              name="chat_id"
              pattern="oc_[a-zA-Z0-9_-]{1,140}"
              maxLength={150}
              defaultValue={editing?.chat_id}
              className={fieldClass}
              placeholder="oc_..."
            />
          </Field>
          <label className="flex gap-2 text-13">
            <input type="checkbox" name="enabled" defaultChecked={editing?.enabled ?? true} />
            启用此接收目标
          </label>
        </Modal>
      )}
    </section>
  );
}

export function ReportDeliveryPanel({
  base,
  reportId,
  reportVersion,
}: {
  base: string;
  reportId: string;
  reportVersion: number;
}) {
  const { data: targets } = useSWR(`${base}notification-targets/all`, () =>
    qualityApi.all<Target>(`${base}notification-targets/`)
  );
  const { data, error, mutate } = useSWR(`${base}reports/${reportId}/deliveries/all`, () =>
    qualityApi.all<Delivery>(`${base}reports/${reportId}/deliveries/`)
  );
  const deliveryPagination = useCollectionPagination(`${base}:deliveries:${reportId}`, data);
  const [selecting, setSelecting] = useState(false),
    [preview, setPreview] = useState<Delivery>(),
    [message, setMessage] = useState("");
  return (
    <section className="space-y-3 border-t border-subtle pt-3">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-13 font-medium">报告投递记录</h3>
        <Button type="button" variant="neutral-primary" onClick={() => setSelecting(true)}>
          准备飞书投递
        </Button>
      </div>
      <p className="text-12 text-secondary">
        仅投递下方预览的摘要，不包含日志或附件。只有明确确认发送后才会联系飞书；收到消息回执后才标为成功。
      </p>
      {(message || error) && (
        <p role="status" className="text-12">
          {message || errorMessage(error)}
        </p>
      )}
      {deliveryPagination.rows.map((row) => (
        <div key={row.id} className="flex flex-wrap items-center justify-between gap-2 text-12">
          <span>
            {row.target_name} · {states[row.status] || row.status} · {row.attempts}次尝试
          </span>
          <Button type="button" variant="neutral-primary" onClick={() => setPreview(row)}>
            {row.status === "sent" ? "查看已发内容" : "查看待发内容"}
          </Button>
        </div>
      ))}
      {data && <Paging {...deliveryPagination.paging} />}
      {selecting && (
        <Modal
          title="准备飞书报告预览"
          onClose={() => setSelecting(false)}
          submitLabel="生成预览，不发送"
          onSubmit={async (form) => {
            const row = await qualityApi.write<Delivery>(`${base}reports/${reportId}/deliveries/`, {
              target_id: form.get("target_id"),
              request_id: crypto.randomUUID(),
              expected_version: reportVersion,
            });
            await mutate();
            setPreview(row);
          }}
        >
          <Field label="接收群 *">
            <select required name="target_id" className={fieldClass}>
              <option value="">请选择当前项目已登记的群</option>
              {targets
                ?.filter((target) => target.enabled)
                .map((target) => (
                  <option key={target.id} value={target.id}>
                    {target.name} · {target.chat_id}
                  </option>
                ))}
            </select>
          </Field>
          <p className="text-12 text-secondary">没有目标时，请由项目经理在“平台集成 → 报告投递目标”登记。</p>
        </Modal>
      )}
      {preview && (
        <Modal
          title={preview.status === "sent" ? "已发送的报告摘要" : "确认飞书接收群与消息内容"}
          onClose={() => setPreview(undefined)}
          submitLabel="确认向此群发送"
          onSubmit={
            preview.status === "sent"
              ? undefined
              : async () => {
                  try {
                    await qualityApi.write(`${base}report-deliveries/${preview.id}/send/`, { confirmed: true });
                    setMessage("飞书已返回消息回执。");
                  } finally {
                    await mutate();
                  }
                }
          }
        >
          <p className="text-13">
            接收群：{preview.target_name} · {preview.chat_id}
          </p>
          <pre className="max-h-80 overflow-auto rounded bg-layer-1 p-3 text-12 whitespace-pre-wrap">
            {preview.text}
          </pre>
          <p className="text-12 text-secondary">
            改变报告或目标后必须重新预览。同一投递记录重试使用同一消息编号；若回执未确认，先在飞书核对，避免重复生成投递。
          </p>
        </Modal>
      )}
    </section>
  );
}
