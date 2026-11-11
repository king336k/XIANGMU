// SPDX-License-Identifier: AGPL-3.0-only
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { useSearchParams } from "react-router";
import useSWR from "swr";
import { useProject } from "@/hooks/store/use-project";
import { SettingsContentWrapper } from "./content-wrapper";
import { UnifiedMembers } from "./unified-members";
import { IntegrationsPanel } from "@/components/quality/integrations-panel";
import { canOpenQualityTab } from "@/components/quality/types";
import { ConnectionSettings } from "@/components/quality/connection-settings";
import { ModelSettings } from "@/components/knowledge/model-settings";
import { qualityApi, errorMessage } from "@/components/quality/api";
import { fieldClass } from "@/components/quality/shared";
import type { Context } from "@/components/quality/types";

export const PlatformManagement = observer(function PlatformManagement({
  section,
}: {
  section: "accounts" | "connections" | "models" | "members" | "sources";
}) {
  const { workspaceSlug } = useParams();
  const [params, setParams] = useSearchParams();
  const { joinedProjectIds, getPartialProjectById } = useProject();
  const selected = params.get("project") || "";
  const projectId = joinedProjectIds.includes(selected) ? selected : "";
  const base = projectId ? `/api/workspaces/${workspaceSlug}/projects/${projectId}/quality/` : "";
  const { data: context, error } = useSWR(
    base && !["connections", "models"].includes(section) ? `${base}context/` : null,
    (url: string) => qualityApi.read<Context>(url)
  );
  const allowed =
    section === "connections"
      ? context?.is_administrator === true
      : section === "sources"
        ? canOpenQualityTab(context, "integrations")
        : context?.can_configure_model === true;
  const title =
    section === "members" || section === "accounts"
      ? "成员与权限"
      : section === "sources"
        ? "报告通知"
        : section === "connections"
          ? "平台连接"
          : "模型配置";
  if (section === "models") {
    return (
      <SettingsContentWrapper hugging>
        <h1 className="platform-page-title mb-3">模型配置</h1>
        <p className="mb-5 text-13 text-secondary">当前工作区的所有项目共用此模型配置。</p>
        <ModelSettings base="" endpoint={`/api/workspaces/${workspaceSlug}/model-configuration/`} />
      </SettingsContentWrapper>
    );
  }
  if (section === "connections") {
    return (
      <SettingsContentWrapper hugging>
        <h1 className="platform-page-title mb-5">平台连接</h1>
        <ConnectionSettings endpoint="/api/quality-auth/connections/" />
      </SettingsContentWrapper>
    );
  }
  return (
    <SettingsContentWrapper hugging>
      <h1 className="platform-page-title mb-5">{title}</h1>
      <label className="mb-5 flex max-w-lg flex-col gap-2 text-13">
        {section === "members" || section === "accounts" ? "权限范围" : "选择项目"}
        <select
          aria-label="选择项目"
          className={fieldClass}
          value={projectId}
          onChange={(event) => {
            const next = new URLSearchParams(params);
            next.set("project", event.target.value);
            setParams(next);
          }}
        >
          <option value="">当前工作区 · 全部项目</option>
          {joinedProjectIds.map((id) => (
            <option key={id} value={id}>
              {getPartialProjectById(id)?.name || id}
            </option>
          ))}
        </select>
      </label>
      {section === "members" || section === "accounts" ? (
        projectId && (error || !context) ? (
          <p role={error ? "alert" : "status"} className="text-13 text-secondary">
            {error ? errorMessage(error) : "正在加载…"}
          </p>
        ) : (
          <UnifiedMembers
            key={projectId}
            workspace={String(workspaceSlug)}
            projectId={projectId}
            context={error ? undefined : context}
            view={params.get("view") || "project"}
            onViewChange={(view) => {
              const next = new URLSearchParams(params);
              next.set("view", view);
              setParams(next);
            }}
          />
        )
      ) : (
        <>
          <p className="mb-5 text-12 text-secondary">
            {section === "sources" ? "配置所选项目测试报告的飞书接收群；不使用飞书时可留空。" : "平台统一模型配置。"}
          </p>
          {!projectId ? (
            <p role="status" className="text-13 text-secondary">
              请选择项目。
            </p>
          ) : error ? (
            <p role="alert" className="text-13 text-danger-primary">
              {errorMessage(error)}
            </p>
          ) : !context ? (
            <p role="status" className="text-13 text-secondary">
              正在加载…
            </p>
          ) : !allowed ? (
            <p role="alert" className="text-13 text-secondary">
              没有配置权限。
            </p>
          ) : section === "sources" ? (
            <IntegrationsPanel key={projectId} base={base} context={context} includeConnections={false} />
          ) : (
            <ModelSettings key={projectId} base={base.replace(/quality\/$/, "knowledge/")} />
          )}
        </>
      )}
    </SettingsContentWrapper>
  );
});
