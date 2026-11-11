import type { IPartialProject } from "@plane/types";
import { Modal } from "@/components/quality/shared";
import { useProject } from "@/hooks/store/use-project";

const ITEMS = [
  ["requirements", "需求", "整理需求与验收目标"],
  ["work_items", "任务", "安排研发任务与跟踪进度"],
  ["defects", "缺陷", "接收问题并跟踪修复"],
  ["quality", "测试", "维护测试用例、计划和执行记录"],
  ["versions", "版本迭代", "规划版本和交付范围"],
  ["knowledge", "文档与知识", "沉淀项目文档与经验"],
];

export function ProjectMenuSettings({
  workspaceSlug,
  project,
  onClose,
}: {
  workspaceSlug: string;
  project: IPartialProject;
  onClose: () => void;
}) {
  const { updateProject } = useProject();
  return (
    <Modal
      title="项目菜单设置"
      width="wide"
      submitLabel="保存设置"
      onClose={onClose}
      onSubmit={async (form) => {
        const visible = new Set(form.getAll("visible_menu_items").map(String));
        if (!visible.size) throw new Error("请至少保留一个项目菜单。");
        await updateProject(workspaceSlug, project.id, {
          hidden_menu_items: ITEMS.filter(([key]) => !visible.has(key)).map(([key]) => key),
        });
        onClose();
      }}
    >
      <p className="mb-1 text-13 font-medium">{project.name}</p>
      <p className="mb-4 text-13 leading-6 text-secondary">
        勾选此项目需要显示的菜单，设置对项目成员统一生效。隐藏菜单不会删除已有数据，也不会改变成员权限。
      </p>
      <div className="divide-y divide-subtle overflow-hidden rounded-md border border-subtle">
        {ITEMS.map(([key, label, description]) => (
          <label
            key={key}
            aria-label={label}
            htmlFor={`project-menu-${project.id}-${key}`}
            className="flex cursor-pointer items-start gap-3 p-3 hover:bg-layer-1"
          >
            <input
              id={`project-menu-${project.id}-${key}`}
              className="mt-1"
              type="checkbox"
              name="visible_menu_items"
              value={key}
              defaultChecked={!project.hidden_menu_items?.includes(key)}
            />
            <span>
              <span className="block text-13 font-medium">{label}</span>
              <span className="mt-1 block text-12 text-secondary">{description}</span>
            </span>
          </label>
        ))}
      </div>
    </Modal>
  );
}
