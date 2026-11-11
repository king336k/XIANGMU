// SPDX-License-Identifier: AGPL-3.0-only
export function MaintenanceMessage() {
  return (
    <div className="space-y-4 text-center">
      <h1 className="text-18 font-semibold">平台服务暂不可用</h1>
      <p className="text-13 text-secondary">请稍后重试。如仍无法访问，请联系管理员。</p>
      <button
        type="button"
        onClick={() => window.location.reload()}
        className="rounded-md border border-subtle px-4 py-2 text-13 hover:bg-layer-1"
      >
        重新加载
      </button>
    </div>
  );
}
