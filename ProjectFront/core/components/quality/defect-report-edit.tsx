import { qualityApi } from "./api";
import { Field, fieldClass, Modal } from "./shared";
import type { Defect } from "./types";

export function DefectReportEdit({
  base,
  value,
  onClose,
  onSaved,
}: {
  base: string;
  value: Defect;
  onClose: () => void;
  onSaved: (value: Defect) => Promise<void>;
}) {
  return (
    <Modal
      title="补充上报信息"
      onClose={onClose}
      onSubmit={async (form) => {
        const updated = await qualityApi.write<Defect>(
          `${base}defects/${value.id}/report/`,
          {
            expected_version: value.edit_version,
            title: form.get("title"),
            description: form.get("description"),
            affected_build: form.get("affected_build"),
          },
          "patch"
        );
        await onSaved(updated);
      }}
    >
      <Field label="缺陷标题 *">
        <input required name="title" maxLength={255} defaultValue={value.title} className={fieldClass} />
      </Field>
      <Field label="重现步骤 / 实际表现">
        <textarea name="description" rows={5} defaultValue={value.description} className={fieldClass} />
      </Field>
      <Field label="影响版本">
        <input name="affected_build" maxLength={255} defaultValue={value.affected_build} className={fieldClass} />
      </Field>
    </Modal>
  );
}
