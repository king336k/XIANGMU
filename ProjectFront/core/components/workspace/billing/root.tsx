// SPDX-License-Identifier: AGPL-3.0-only
import { PlaneVersionNumber } from "@/components/global/version-number";
export function BillingRoot() {
  return (
    <section className="space-y-5">
      <h2 className="text-18 font-semibold">版本与许可</h2>
      <p className="text-13 text-secondary">本平台为本地部署的研发与测试管理系统。</p>
      <div className="rounded-md border border-subtle p-4">
        <PlaneVersionNumber />
      </div>
    </section>
  );
}
