import { useCollectionPagination } from "./use-collection-pagination";
// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass, Modal, Paging } from "./shared";
import { can } from "./types";
import type { Context, Plan } from "./types";

type Resource = {
  id: string;
  name: string;
  kind: string;
  status: string;
  build: string;
  description: string;
  agent_id: string | null;
  source_instance: string;
  external_id: string;
  edit_version: number;
};
type Readiness = {
  ready: boolean;
  errors: string[];
  notice: string;
  checked_at: string;
  resources: { id: string; name: string; errors: string[] }[];
};
const kinds: Record<string, string> = {
  robot: "机器人/设备",
  daq_station: "采集工作站",
  server: "测试服务器",
  environment: "测试环境",
  other: "其他",
};
const statuses: Record<string, string> = {
  available: "可用",
  offline: "离线",
  maintenance: "维护中",
  disabled: "已停用",
};

export function TestResourcesPanel({ base, context }: { base: string; context: Context }) {
  const { data, error, mutate } = useSWR(`${base}test-resources/all`, () =>
    qualityApi.all<Resource>(`${base}test-resources/`)
  );
  const { data: agents } = useSWR(`${base}field-agents/all`, () =>
    qualityApi.all<{ id: string; name: string }>(`${base}field-agents/`)
  );
  const pagination = useCollectionPagination(`${base}:test-resources`, data);
  const [editing, setEditing] = useState<Resource | null | undefined>();
  return (
    <section className="space-y-3 border-t border-subtle pt-5">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-14 font-medium">测试执行资源</h3>
        {can(context, "manage_test_plan") && (
          <Button variant="neutral-primary" onClick={() => setEditing(null)}>
            登记测试资源
          </Button>
        )}
      </div>
      <p className="text-12 text-secondary">
        登记设备、版本与环境，再在计划里按需选择。登记状态由测试安排人员维护；关联现场代理后还会检查近期心跳。资源可用不等于测试通过。
      </p>
      {error && (
        <p role="alert" className="text-12 text-danger-primary">
          {errorMessage(error)}
        </p>
      )}
      {!data?.length && (
        <p className="text-12 text-secondary">尚无测试资源。简单手工测试可直接执行，不强制登记设备。</p>
      )}
      {pagination.rows.map((row) => (
        <div
          key={row.id}
          className="flex flex-wrap items-center justify-between gap-3 rounded border border-subtle p-3 text-12"
        >
          <div>
            <p className="font-medium">
              {row.name} · {kinds[row.kind]}
            </p>
            <p className="mt-1 text-secondary">
              {statuses[row.status]} · {row.build || "未固定资源版本"}
              {row.source_instance && ` · 来源 ${row.source_instance} / ${row.external_id}`}
            </p>
          </div>
          {can(context, "manage_test_plan") && (
            <Button variant="neutral-primary" onClick={() => setEditing(row)}>
              调整资源
            </Button>
          )}
        </div>
      ))}
      {data && <Paging {...pagination.paging} />}
      {editing !== undefined && (
        <Modal
          title={editing ? "调整测试资源" : "登记测试资源"}
          onClose={() => setEditing(undefined)}
          onSubmit={async (form) => {
            await qualityApi.write(
              `${base}test-resources/${editing ? editing.id + "/" : ""}`,
              {
                name: form.get("name"),
                kind: form.get("kind"),
                status: form.get("status"),
                build: form.get("build"),
                description: form.get("description"),
                agent_id: form.get("agent_id") || null,
                ...(editing ? { expected_version: editing.edit_version } : {}),
              },
              editing ? "patch" : "post"
            );
            await mutate();
          }}
        >
          <Field label="资源名称 *">
            <input required name="name" maxLength={255} defaultValue={editing?.name} className={fieldClass} />
          </Field>
          <Field label="资源类型">
            <select name="kind" defaultValue={editing?.kind || "environment"} className={fieldClass}>
              {Object.entries(kinds).map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="当前状态">
            <select name="status" defaultValue={editing?.status || "available"} className={fieldClass}>
              {Object.entries(statuses).map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="资源版本（可选，填写后必须与计划被测版本相同）">
            <input name="build" maxLength={120} defaultValue={editing?.build} className={fieldClass} />
          </Field>
          <Field label="关联现场代理（可选）">
            <select name="agent_id" defaultValue={editing?.agent_id || ""} className={fieldClass}>
              <option value="">不依赖现场心跳</option>
              {agents?.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="资源说明">
            <textarea
              name="description"
              rows={3}
              maxLength={4000}
              defaultValue={editing?.description}
              className={fieldClass}
            />
          </Field>
        </Modal>
      )}
    </section>
  );
}

export function PlanPreflight({
  base,
  plan,
  context,
  onSaved,
}: {
  base: string;
  plan: Plan;
  context: Context;
  onSaved: () => Promise<unknown>;
}) {
  const { data, error, mutate } = useSWR(
    `${base}plans/${plan.id}/preflight/`,
    (url: string) => qualityApi.read<Readiness>(url),
    { refreshInterval: 30000 }
  );
  const { data: resources } = useSWR(`${base}test-resources/all`, () =>
    qualityApi.all<Resource>(`${base}test-resources/`)
  );
  const [selecting, setSelecting] = useState(false);
  if (!resources?.length && !data?.resources.length && !error) return null;
  return (
    <section className="space-y-2 rounded border border-subtle p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-13 font-medium">
          执行前检查 · {data ? (data.ready ? "资源就绪" : "有待解决项") : "正在检查"}
        </h3>
        <div className="flex gap-2">
          <Button variant="neutral-primary" onClick={() => void mutate()}>
            重新检查
          </Button>
          {can(context, "manage_test_plan") && ["pending", "ready", "returned"].includes(plan.status) && (
            <Button variant="neutral-primary" onClick={() => setSelecting(true)}>
              安排执行资源
            </Button>
          )}
        </div>
      </div>
      {error && (
        <p role="alert" className="text-12 text-danger-primary">
          {errorMessage(error)}
        </p>
      )}
      <p className="text-12 text-secondary">
        {data?.resources.length ? data.resources.map((row) => row.name).join("、") : "本计划未指定必需资源。"}
      </p>
      {data?.errors.map((message) => (
        <p key={message} className="text-12 text-danger-primary">
          {message}
        </p>
      ))}
      <details className="text-12 text-secondary">
        <summary className="cursor-pointer">检查范围</summary>
        <p className="mt-2">{data?.notice} · 记录执行结果时保存当时的资源检查快照。</p>
      </details>
      {selecting && (
        <Modal
          title="安排执行资源"
          onClose={() => setSelecting(false)}
          onSubmit={async (form) => {
            await qualityApi.write(`${base}plans/${plan.id}/resources/`, {
              expected_version: plan.workflow_version,
              resource_ids: form.getAll("resource_ids"),
            });
            await mutate();
            await onSaved();
          }}
        >
          <p className="text-12 text-secondary">
            可不选择资源。有执行记录后不再更换资源，需复制新计划；不会把资源状态当成测试结果。
          </p>
          {resources?.map((row) => (
            <label key={row.id} className="flex gap-2 text-13">
              <input
                type="checkbox"
                name="resource_ids"
                value={row.id}
                defaultChecked={data?.resources.some((selected) => selected.id === row.id)}
              />
              {row.name} · {statuses[row.status]} · {row.build || "不限制版本"}
            </label>
          ))}
        </Modal>
      )}
    </section>
  );
}
