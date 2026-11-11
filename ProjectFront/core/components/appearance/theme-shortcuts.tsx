import { Palette } from "lucide-react";
import { CustomMenu } from "@plane/ui";

export function ThemeShortcuts({ onOpen }: { onOpen: () => void }) {
  return (
    <CustomMenu.MenuItem onClick={onOpen} className="flex items-center gap-2">
      <Palette className="size-3.5 shrink-0" />
      主题
    </CustomMenu.MenuItem>
  );
}
