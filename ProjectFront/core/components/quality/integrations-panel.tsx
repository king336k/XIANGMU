// SPDX-License-Identifier: AGPL-3.0-only
import { ConnectionSettings } from "./connection-settings";
import { ProjectSourceFields } from "./project-source-fields";
import { IntegrationRecords } from "./integration-records";
import { CatalogPanel } from "./catalog-panel";
import { useState } from "react";
import useSWR from "swr";
import { Button } from "@plane/ui";
import { qualityApi, errorMessage } from "./api";
import { Field, fieldClass, Modal } from "./shared";
import type { Context } from "./types";
import { can } from "./types";
import { NotificationTargetsPanel } from "./report-delivery-panel";
type Mapping = {
  id: string;
  source_instance: string;
  active: boolean;
  external_project_id?: number;
  external_user_id?: number;
  name?: string;
  task_id?: number;
  session_id?: string;
  package_id?: string;
  authority_configured?: boolean;
};
type Inventory = {
  projects: Mapping[];
  identities: Mapping[];
  bindings: Mapping[];
  notice: string;
  counts?: { active_identity: number };
};
export function IntegrationsPanel({
  base,
  context,
  includeConnections = true,
}: {
  base: string;
  context: Context;
  includeConnections?: boolean;
}) {
  const { data, error, mutate } = useSWR(`${base}integrations/?summary=1`, (url: string) =>
    qualityApi.read<Inventory>(url)
  );
  const [kind, setKind] = useState<string>(),
    [message, setMessage] = useState("");
  const canManage = context.is_manager || can(context, "manage_roles");
  const toggle = async (type: string, row: Mapping) => {
    try {
      await qualityApi.write(`${base}integrations/`, {
        kind: type,
        id: row.id,
        expected_active: row.active,
        active: !row.active,
      });
      await mutate();
    } catch (e) {
      setMessage(errorMessage(e));
    }
  };
  return (
    <section className="space-y-5">
      <h2 className="text-16 font-semibold">来源关联</h2>
      {(error || message) && (
        <p role="status" className="text-13">
          {message || errorMessage(error)}
        </p>
      )}
      {canManage && (
        <div className="flex flex-wrap gap-2">
          <Button variant="neutral-primary" onClick={() => setKind("project")}>
            关联数据管理平台项目
          </Button>
          <Button variant="neutral-primary" onClick={() => setKind("check")}>
            核验采集来源
          </Button>
        </div>
      )}
      {data && (
        <details className="rounded-md border border-subtle p-4">
          <summary className="cursor-pointer text-14 font-medium">
            账号互认配置{" "}
            <span className="font-normal ml-2 text-12 text-secondary">
              {(data.counts?.active_identity ?? data.identities.filter((row) => row.active).length) > 0
                ? `已关联 ${data.counts?.active_identity ?? data.identities.filter((row) => row.active).length} 位成员`
                : "未配置"}
            </span>
          </summary>
          <div className="mt-3 space-y-3">
            <p className="text-12 leading-5 text-secondary">来源账号与本项目成员的对应关系。</p>
            {canManage && (
              <Button variant="neutral-primary" onClick={() => setKind("identity")}>
                关联外部账号
              </Button>
            )}
            <IntegrationRecords
              base={base}
              kind="identity"
              title="账号关联"
              canManage={canManage}
              revision={data}
              onToggle={toggle}
            />
          </div>
        </details>
      )}
      <IntegrationRecords
        base={base}
        kind="project"
        title="项目来源"
        canManage={canManage}
        revision={data}
        onToggle={toggle}
      />
      <IntegrationRecords
        base={base}
        kind="binding"
        title="已核对采集来源"
        canManage={canManage}
        revision={data}
        onToggle={toggle}
      />
      <CatalogPanel
        base={base}
        sources={data?.projects || []}
        onSynced={mutate}
        canImport={can(context, "manage_test")}
      />
      {includeConnections && <ConnectionSettings base={base} />}
      {context.is_manager && <NotificationTargetsPanel base={base} />}
      {kind && (
        <Modal
          title={kind === "project" ? "关联数据管理平台项目" : kind === "identity" ? "关联外部账号" : "采集来源核验"}
          onClose={() => setKind(undefined)}
          onSubmit={async (form) => {
            const source_instance = String(form.get("source_instance"));
            if (kind === "project")
              await qualityApi.write(`${base}daq/project-mapping/`, {
                source_instance,
                external_project_id: Number(form.get("external_project_id")),
                name: String(form.get("external_project_name") || ""),
              });
            if (kind === "identity")
              await qualityApi.write(`${base}daq/identities/`, {
                source_instance,
                external_user_id: Number(form.get("external_user_id")),
                user_id: form.get("user_id"),
              });
            if (kind === "check") {
              const response = await qualityApi.write<{ notice: string }>(`${base}integrations/check/`, {
                source_instance,
                task_id: Number(form.get("task_id")),
                source_session_id: form.get("source_session_id") || "",
              });
              setMessage(`来源核验通过。${response.notice}`);
            }
            await mutate();
          }}
        >
          <ProjectSourceFields base={base} project={kind === "project"} />
          {kind === "identity" && (
            <>
              <Field label="外部用户编号 *">
                <input required type="number" min={1} name="external_user_id" className={fieldClass} />
              </Field>
              <Field label="本项目已有成员 *">
                <select required name="user_id" className={fieldClass}>
                  <option value="">请选择</option>
                  {context.members.map((row) => (
                    <option key={row.id} value={row.id}>
                      {row.name}
                    </option>
                  ))}
                </select>
              </Field>
            </>
          )}
          {kind === "check" && (
            <>
              <Field label="采集任务编号 *">
                <input required type="number" min={1} name="task_id" className={fieldClass} />
              </Field>
              <Field label="Session编号（可选）">
                <input name="source_session_id" maxLength={255} className={fieldClass} />
              </Field>
            </>
          )}
        </Modal>
      )}
    </section>
  );
}
