// SPDX-License-Identifier: AGPL-3.0-only
import { observer } from "mobx-react";
import { Navigate, useParams, useLocation } from "react-router";
import { useProject } from "@/hooks/store/use-project";
import { useProjectRoutePaths } from "@/app/compat/next/navigation";
export const ProjectShortLink = observer(function ProjectShortLink() {
  const { workspaceSlug } = useParams();
  const location = useLocation();
  const { shortPath } = useProjectRoutePaths();
  const { projectMap, loader } = useProject();
  const canonical = shortPath(location.pathname + location.search + location.hash);
  if (canonical !== location.pathname + location.search + location.hash) return <Navigate replace to={canonical} />;
  if (!Object.keys(projectMap).length || loader === "init-loader")
    return (
      <p role="status" className="p-6 text-13 text-secondary">
        正在定位项目…
      </p>
    );
  return (
    <div className="space-y-3 p-6 text-13">
      <h1 className="text-18 font-semibold">无法打开此项目</h1>
      <p className="text-secondary">请检查项目编号或访问权限。</p>
      <a className="text-accent-primary" href={`/${workspaceSlug}/projects/`}>
        返回项目目录
      </a>
    </div>
  );
});
