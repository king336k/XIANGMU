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
      {includeConnections && <ConnectionSettings base={base} />}
      <NotificationTargetsPanel base={base} />
    </section>
  );
}
