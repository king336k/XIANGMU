// SPDX-License-Identifier: AGPL-3.0-only
import type { ComponentProps } from "react";
import { forwardRef } from "react";
import { Link } from "react-router";
import { observer } from "mobx-react";
import { ControlLink } from "@plane/ui";
import { useProjectRoutePaths } from "@/app/compat/next/navigation";
export const ProjectRouteLink = observer(
  forwardRef<HTMLAnchorElement, ComponentProps<typeof Link>>(function ProjectRouteLink({ to, ...props }, ref) {
    const { shortPath } = useProjectRoutePaths();
    const destination =
      typeof to === "string" ? shortPath(to) : { ...to, pathname: to.pathname ? shortPath(to.pathname) : to.pathname };
    return <Link {...props} to={destination} ref={ref} />;
  })
);
export const ProjectControlLink = observer(
  forwardRef<HTMLAnchorElement, ComponentProps<typeof ControlLink>>(function ProjectControlLink(
    { href, ...props },
    ref
  ) {
    const { shortPath } = useProjectRoutePaths();
    return <ControlLink {...props} href={shortPath(href)} ref={ref} />;
  })
);
