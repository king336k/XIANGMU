import { Modal, Field, fieldClass } from "@/components/quality/shared";

export function RenameDialog({
  title,
  label,
  name,
  maxLength,
  onRename,
  onClose,
}: {
  title: string;
  label: string;
  name: string;
  maxLength: number;
  onRename: (name: string) => Promise<unknown>;
  onClose: () => void;
}) {
  return (
    <Modal
      title={title}
      width="compact"
      onClose={onClose}
      submitLabel="保存名称"
      onSubmit={async (form) => {
        const next = String(form.get("name") || "").trim();
        if (!next) throw Error("请输入名称。");
        if (next.length > maxLength) throw Error(`名称不能超过${maxLength}个字符。`);
        if (next !== name) await onRename(next);
      }}
    >
      <Field label={label}>
        <input
          name="name"
          aria-label={label}
          defaultValue={name}
          required
          maxLength={maxLength}
          className={fieldClass}
        />
      </Field>
    </Modal>
  );
}
