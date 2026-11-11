import { useCollectionPagination } from "./use-collection-pagination";
import { renderNumericDateTime } from "@plane/utils";
// SPDX-License-Identifier: AGPL-3.0-only
import { useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass, Modal, Paging } from "./shared";
import type { Context } from "./types";
import { TestResourcesPanel } from "./test-resources-panel";
type Snapshot = {
  id: string;
  snapshot: Record<string, unknown>;
  review_status: string;
  review_note: string;
  created_at: string;
  trusted_as_test_result: false;
};
type Agent = {
  id: string;
  name: string;
  owner_id: string;
  owner_name: string;
  source_instance: string;
  enabled: boolean;
  online: boolean;
  edit_version: number;
  credential_present: boolean;
  credential_expires_at: string | null;
  last_seen_at: string | null;
  latest_snapshot: Snapshot | null;
};
export function FieldResourcesPanel({ base, context }: { base: string; context: Context }) {
  const pagination = useCollectionPagination(`${base}:field-agents`);
  const { data, error, mutate } = useSWR(
    `${base}field-agents/?${pagination.query}`,
    (url: string) => qualityApi.read<{ results: Agent[]; count: number }>(url),
    { refreshInterval: 15000 }
  );
  const [credentialAgent, setCredentialAgent] = useState<Agent>();
  const [issuedToken, setIssuedToken] = useState("");
  const [creating, setCreating] = useState(false),
    [selected, setSelected] = useState<Agent>(),
    [review, setReview] = useState<Snapshot>(),
    [message, setMessage] = useState("");
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-16 font-semibold">采集工作站</h2>
        <Button
          variant="neutral-primary"
          onClick={() => {
            void qualityApi
              .download(`${base}field-agent-client/`, "native-field-observer.zip")
              .catch((e) => setMessage(errorMessage(e)));
          }}
        >
          下载现场观察客户端
        </Button>
        {context.is_manager && <Button onClick={() => setCreating(true)}>登记采集工作站</Button>}
      </div>
      <p className="text-12 text-secondary">
        登记采集电脑或代理，查看在线状态与现场快照。测试设备和环境在下方管理；资源在线不代表采集或测试已完成。
      </p>
      {(error || message) && (
        <p role="alert" className="text-13 text-danger-primary">
          {message || errorMessage(error)}
        </p>
      )}
      {!data?.results.length && (
        <p className="text-13 text-secondary">尚未登记现场资源。登记后由对应数采员/可信接入端上报心跳与脱敏快照。</p>
      )}
      {data?.results.map((row) => (
        <article
          key={row.id}
          className="flex flex-wrap items-center justify-between gap-3 rounded border border-subtle p-4"
        >
          <div>
            <h3 className="text-14 font-medium">{row.name}</h3>
            <p className="mt-1 text-12 text-secondary">
              {row.owner_name} · {row.enabled ? (row.online ? "在线" : "未收到近期心跳") : "已停用"} ·{" "}
              {row.last_seen_at ? renderNumericDateTime(row.last_seen_at) : "尚无心跳"}
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="neutral-primary" onClick={() => setSelected(row)}>
              查看现场快照
            </Button>
            {context.is_manager && (
              <>
                <Button
                  variant="neutral-primary"
                  disabled={!row.enabled}
                  onClick={() => {
                    setCredentialAgent(row);
                    setIssuedToken("");
                  }}
                >
                  接入设置
                </Button>
                <Button
                  variant="neutral-primary"
                  disabled={!row.enabled}
                  onClick={() =>
                    void qualityApi
                      .download(`${base}field-agents/${row.id}/install-package/`, `field-observer-${row.id}.zip`)
                      .catch((e) => setMessage(errorMessage(e)))
                  }
                >
                  下载此资源部署包
                </Button>
                <Button
                  variant="neutral-primary"
                  onClick={async () => {
                    try {
                      await qualityApi.write(
                        `${base}field-agents/${row.id}/`,
                        { enabled: !row.enabled, expected_version: row.edit_version },
                        "patch"
                      );
                      await mutate();
                    } catch (e) {
                      setMessage(errorMessage(e));
                    }
                  }}
                >
                  {row.enabled ? "停用资源" : "启用资源"}
                </Button>
              </>
            )}
          </div>
        </article>
      ))}
      {data && <Paging {...pagination.paging} count={data.count} />}
      <TestResourcesPanel base={base} context={context} />
      {creating && (
        <Modal
          title="登记采集工作站"
          onClose={() => setCreating(false)}
          onSubmit={async (form) => {
            await qualityApi.write(`${base}field-agents/`, {
              name: form.get("name"),
              owner_id: form.get("owner_id"),
              source_instance: form.get("source_instance") || "",
            });
            await mutate();
          }}
        >
          <Field label="名称 *">
            <input required name="name" maxLength={200} className={fieldClass} />
          </Field>
          <Field label="负责数采员 *">
            <select required name="owner_id" className={fieldClass}>
              <option value="">请选择</option>
              {context.members
                .filter(
                  (row) =>
                    !context.business_roles_enabled ||
                    (row.business_roles || [row.business_role]).some(
                      (role) => typeof role === "string" && ["PLATFORM_ADMIN", "REPORTER"].includes(role)
                    )
                )
                .map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.name}
                  </option>
                ))}
            </select>
          </Field>
          <Field label="可信来源实例">
            <input
              name="source_instance"
              maxLength={120}
              className={fieldClass}
              placeholder="与当前DAQ反馈服务的实例名一致"
            />
          </Field>
        </Modal>
      )}
      {credentialAgent && (
        <Modal
          title="设置现场资源接入凭据"
          onClose={() => {
            setCredentialAgent(undefined);
            setIssuedToken("");
          }}
        >
          <p className="text-13">
            只允许向“{credentialAgent.name}
            ”上报脱敏心跳和快照，不能查看其他项目、创建缺陷或修改测试结果。30天后过期；轮换后旧凭据立即失效。
          </p>
          {!issuedToken && (
            <Button
              type="button"
              onClick={async () => {
                try {
                  const result = await qualityApi.write<{ token: string }>(
                    `${base}field-agents/${credentialAgent.id}/credential/`,
                    { expected_version: credentialAgent.edit_version }
                  );
                  setIssuedToken(result.token);
                  await mutate();
                } catch (e) {
                  setMessage(errorMessage(e));
                }
              }}
            >
              生成资源专用凭据
            </Button>
          )}
          {issuedToken && (
            <Field label="仅本次显示：在客户端环境设置 FIELD_AGENT_TOKEN">
              <input type="password" readOnly value={issuedToken} autoComplete="off" className={fieldClass} />
            </Field>
          )}
        </Modal>
      )}
      {selected && (
        <Modal title={selected.name} onClose={() => setSelected(undefined)}>
          <p className="text-12 text-secondary">
            数采员：{selected.owner_name} · 来源：{selected.source_instance || "本机会话上报"}
          </p>
          <p className="text-12">资源编号：{selected.id}</p>
          {selected.latest_snapshot ? (
            <>
              <p className="text-12">
                快照时间：{renderNumericDateTime(selected.latest_snapshot.created_at)} ·{" "}
                {
                  ({ pending: "待复核", accepted: "观察已采纳", rejected: "已拒绝" } as Record<string, string>)[
                    selected.latest_snapshot.review_status
                  ]
                }
              </p>
              <pre className="max-h-80 overflow-auto rounded bg-layer-1 p-3 text-12">
                <code>{JSON.stringify(selected.latest_snapshot.snapshot, null, 2)}</code>
              </pre>
              <p className="text-12 text-secondary">
                现场快照不会自动成为测试通过依据。{selected.latest_snapshot.review_note}
              </p>
              {context.is_manager && selected.latest_snapshot.review_status === "pending" && (
                <Button variant="neutral-primary" onClick={() => setReview(selected.latest_snapshot!)}>
                  复核候选快照
                </Button>
              )}
            </>
          ) : (
            <p className="text-13">尚未收到实际快照，不能据此判断在线或采集成功。</p>
          )}
        </Modal>
      )}
      {review && (
        <Modal
          title="复核现场候选证据"
          onClose={() => setReview(undefined)}
          onSubmit={async (form) => {
            await qualityApi.write(`${base}telemetry/${review.id}/review/`, {
              decision: form.get("decision"),
              note: form.get("note"),
            });
            setSelected(undefined);
            await mutate();
          }}
        >
          <Field label="决定">
            <select name="decision" className={fieldClass}>
              <option value="accept">采纳观察（不代表测试通过）</option>
              <option value="reject">拒绝</option>
            </select>
          </Field>
          <Field label="复核依据 *">
            <textarea required name="note" rows={3} maxLength={4000} className={fieldClass} />
          </Field>
        </Modal>
      )}
    </section>
  );
}
