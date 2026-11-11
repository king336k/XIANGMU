// SPDX-License-Identifier: AGPL-3.0-only
import { ConnectionSettings } from "./connection-settings";
import { NotificationTargetsPanel } from "./report-delivery-panel";
import type { Context } from "./types";

export function IntegrationsPanel({
  base,
  includeConnections = true,
}: {
  base: string;
  context: Context;
  includeConnections?: boolean;
}) {
  return (
    <section className="space-y-5">
      <h2 className="text-16 font-semibold">协作服务</h2>
      <p className="text-13 text-secondary">项目、任务与成员由本平台独立管理。DAQ 可向已授权项目提交问题和现场材料。</p>
      {includeConnections && <ConnectionSettings base={base} />}
      <NotificationTargetsPanel base={base} />
    </section>
  );
}
