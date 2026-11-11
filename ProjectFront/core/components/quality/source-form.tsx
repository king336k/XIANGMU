// SPDX-License-Identifier: AGPL-3.0-only
import { qualityApi } from "./api";
import { Field, fieldClass, Modal } from "./shared";

export function SourceForm({
  base,
  onClose,
  onSaved,
}: {
  base: string;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}) {
  return (
    <Modal
      title="登记采集来源缺陷"
      onClose={onClose}
      onSubmit={async (form) => {
        await qualityApi.write(`${base}source-defects/`, Object.fromEntries(form.entries()));
        await onSaved();
      }}
    >
      <Field label="缺陷标题 *">
        <input name="title" required maxLength={255} className={fieldClass} />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="来源系统 *">
          <input name="source_system" required maxLength={64} placeholder="例如 daq" className={fieldClass} />
        </Field>
        <Field label="来源实例 *">
          <input
            name="source_instance"
            required
            maxLength={120}
            placeholder="例如现场环境名称"
            className={fieldClass}
          />
        </Field>
        <Field label="记录类型 *">
          <input name="record_type" required maxLength={64} placeholder="例如 session" className={fieldClass} />
        </Field>
        <Field label="来源记录编号 *">
          <input name="record_id" required maxLength={255} className={fieldClass} />
        </Field>
        <Field label="任务编号">
          <input name="task_id" maxLength={255} className={fieldClass} />
        </Field>
        <Field label="数据包编号">
          <input name="package_id" maxLength={255} className={fieldClass} />
        </Field>
      </div>
      <Field label="设备标识">
        <input name="device" maxLength={255} className={fieldClass} />
      </Field>
      <Field label="异常描述">
        <textarea name="description" maxLength={20000} rows={3} className={fieldClass} />
      </Field>
    </Modal>
  );
}
