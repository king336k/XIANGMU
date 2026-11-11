import { Avatar } from "@plane/ui";
import Link from "next/link";
import { profileWorkItemsHref } from "./overview/links";
/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { PanelRightClose } from "lucide-react";
import { profileSidebarWidth } from "./sidebar-width";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import { Disclosure, Transition } from "@headlessui/react";
// plane imports
import { useOutsideClickDetector } from "@plane/hooks";
import { useTranslation } from "@plane/i18n";
import { Logo } from "@plane/propel/emoji-icon-picker";
import { IconButton } from "@plane/propel/icon-button";
import { EditIcon, ChevronDownIcon } from "@plane/propel/icons";
import { Tooltip } from "@plane/propel/tooltip";
import type { IUserProfileProjectSegregation } from "@plane/types";
import { Loader } from "@plane/ui";
import { cn, renderFormattedDate, getFileURL } from "@plane/utils";
// components
import { CoverImage } from "@/components/common/cover-image";
// hooks
import { useAppTheme } from "@/hooks/store/use-app-theme";
import { useCommandPalette } from "@/hooks/store/use-command-palette";
import { useProject } from "@/hooks/store/use-project";
import { useUser } from "@/hooks/store/user";
import { usePlatformOS } from "@/hooks/use-platform-os";
// components

type TProfileSidebar = {
  userProjectsData: IUserProfileProjectSegregation | undefined;
  className?: string;
};

export const ProfileSidebar = observer(function ProfileSidebar(props: TProfileSidebar) {
  const { userProjectsData, className = "" } = props;
  // refs
  const ref = useRef<HTMLDivElement>(null);
  // router
  const { userId, workspaceSlug } = useParams();
  // store hooks
  const { data: currentUser } = useUser();
  const { profileSidebarCollapsed, toggleProfileSidebar } = useAppTheme();
  const { getProjectById } = useProject();
  const { toggleProfileSettingsModal } = useCommandPalette();
  const { isMobile } = usePlatformOS();
  const { t } = useTranslation();
  // derived values
  const userData = userProjectsData?.user_data;
  const [width, setWidth] = useState(300);
  const resizeSession = useRef<{ width: number; x: number } | null>(null);
  const widthRef = useRef(300);
  const storageKey = `profile-sidebar-width:${workspaceSlug}:${currentUser?.id || "local"}`;
  const availableWidth = () =>
    ref.current?.parentElement?.clientWidth || (typeof window === "undefined" ? 1200 : window.innerWidth);
  const applyWidth = (next: number) => {
    widthRef.current = next;
    setWidth(next);
  };
  const saveWidth = () => {
    try {
      localStorage.setItem(storageKey, String(widthRef.current));
    } catch {
      /* 本地偏好不可写时仍可调宽。 */
    }
  };
  useEffect(() => {
    let restored = 300;
    try {
      restored = Number(localStorage.getItem(storageKey) || 300);
    } catch {
      /* 使用默认宽度。 */
    }
    const next = profileSidebarWidth(restored, 0, 0, ref.current?.parentElement?.clientWidth || window.innerWidth);
    widthRef.current = next;
    setWidth(next);
  }, [storageKey]);

  useOutsideClickDetector(ref, () => {
    if (profileSidebarCollapsed === false) {
      if (window.innerWidth < 768) {
        toggleProfileSidebar();
      }
    }
  });

  const userDetails = [
    {
      i18n_label: "profile.details.joined_on",
      value: renderFormattedDate(userData?.date_joined ?? ""),
    },
  ];

  useEffect(() => {
    let narrow = window.innerWidth < 768;
    toggleProfileSidebar(narrow);
    const handleResize = () => {
      const next = window.innerWidth < 768;
      if (!next) {
        const clamped = profileSidebarWidth(
          widthRef.current,
          0,
          0,
          ref.current?.parentElement?.clientWidth || window.innerWidth
        );
        widthRef.current = clamped;
        setWidth(clamped);
      }
      if (next !== narrow) {
        narrow = next;
        toggleProfileSidebar(next);
      }
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [toggleProfileSidebar]);

  if (profileSidebarCollapsed) return null;
  return (
    <aside
      ref={ref}
      aria-label="个人信息与项目统计"
      className={cn(
        "profile-sidebar absolute inset-y-0 right-0 z-20 h-full w-full shrink-0 border-l border-subtle bg-surface-1 md:relative md:inset-auto",
        className
      )}
      style={{ "--profile-sidebar-width": `${width}px` } as CSSProperties}
    >
      <div
        role="separator"
        tabIndex={0}
        aria-label="调整个人信息栏宽度"
        aria-orientation="vertical"
        aria-valuemin={240}
        aria-valuemax={profileSidebarWidth(440, 0, 0, availableWidth())}
        aria-valuenow={width}
        title="左右拖动调宽，双击恢复默认宽度"
        className="focus-visible:outline-accent-primary absolute inset-y-0 -left-1 z-30 hidden w-2 cursor-col-resize touch-none rounded hover:bg-accent-subtle focus-visible:outline-2 md:block"
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          event.preventDefault();
          resizeSession.current = { width: ref.current?.getBoundingClientRect().width || width, x: event.clientX };
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          const initial = resizeSession.current;
          if (initial) applyWidth(profileSidebarWidth(initial.width, initial.x, event.clientX, availableWidth()));
        }}
        onPointerUp={(event) => {
          if (!resizeSession.current) return;
          resizeSession.current = null;
          event.currentTarget.releasePointerCapture(event.pointerId);
          saveWidth();
        }}
        onLostPointerCapture={() => {
          resizeSession.current = null;
        }}
        onPointerCancel={() => {
          resizeSession.current = null;
        }}
        onDoubleClick={() => {
          applyWidth(profileSidebarWidth(300, 0, 0, availableWidth()));
          saveWidth();
        }}
        onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          const requested =
            event.key === "Home" ? 240 : event.key === "End" ? 440 : width + (event.key === "ArrowLeft" ? 20 : -20);
          applyWidth(profileSidebarWidth(requested, 0, 0, availableWidth()));
          saveWidth();
        }}
      />
      <button
        type="button"
        aria-label="收起个人信息栏"
        title="收起个人信息栏"
        onClick={() => toggleProfileSidebar(true)}
        className="shadow-sm absolute top-3 left-3 z-10 rounded-md bg-surface-1 p-1.5 text-secondary hover:text-primary"
      >
        <PanelRightClose className="size-4" />
      </button>
      <div className="vertical-scrollbar scrollbar-md h-full min-w-0 overflow-x-hidden overflow-y-auto">
        {userProjectsData ? (
          <>
            <div className="relative h-[110px]">
              {currentUser?.id === userId && (
                <div className="absolute top-3.5 right-3.5">
                  <IconButton
                    variant="secondary"
                    icon={EditIcon}
                    onClick={() =>
                      toggleProfileSettingsModal({
                        activeTab: "general",
                        isOpen: true,
                      })
                    }
                  />
                </div>
              )}
              <CoverImage
                src={userData?.cover_image_url ?? undefined}
                alt={userData?.display_name}
                className="h-[110px] w-full"
                showDefaultWhenEmpty
              />
              <div className="absolute -bottom-[26px] left-5 h-[52px] w-[52px] rounded-sm">
                {userData?.avatar_url && userData?.avatar_url !== "" ? (
                  <Avatar src={getFileURL(userData.avatar_url)} name={userData.display_name} size={52} shape="square" />
                ) : (
                  <div className="flex h-[52px] w-[52px] items-center justify-center rounded-sm bg-accent-primary text-on-color capitalize">
                    {userData?.first_name?.[0]}
                  </div>
                )}
              </div>
            </div>
            <div className="px-5">
              <div className="mt-[38px]">
                <h4 className="text-16 font-semibold">
                  {userData?.first_name} {userData?.last_name}
                </h4>
                {userData?.display_name &&
                  userData.display_name !== `${userData.first_name} ${userData.last_name || ""}`.trim() && (
                    <h6 className="text-13 text-secondary">{userData.display_name}</h6>
                  )}
              </div>
              <div className="mt-6 space-y-5">
                {userDetails.map((detail) => (
                  <div key={detail.i18n_label} className="flex items-center gap-4 text-13">
                    <div className="w-2/5 flex-shrink-0 text-secondary">{t(detail.i18n_label)}</div>
                    <div className="w-3/5 font-medium break-words">{detail.value}</div>
                  </div>
                ))}
              </div>
              <div className="mt-9 divide-y divide-subtle">
                {userProjectsData.project_data.map((project, index) => {
                  const projectDetails = getProjectById(project.id);

                  const completedIssuePercentage =
                    project.assigned_issues === 0
                      ? 0
                      : Math.round((project.completed_issues / project.assigned_issues) * 100);

                  if (!projectDetails) return null;

                  return (
                    <Disclosure key={project.id} as="div" className={`${index === 0 ? "pb-3" : "py-3"}`}>
                      {({ open }) => (
                        <div className="w-full">
                          <Disclosure.Button className="flex w-full items-center justify-between gap-2">
                            <div className="flex w-3/4 items-center gap-2">
                              <span className="grid h-7 w-7 flex-shrink-0 place-items-center">
                                <Logo logo={projectDetails.logo_props} />
                              </span>
                              <div className="truncate text-13 font-medium break-words">{projectDetails.name}</div>
                            </div>
                            <div className="flex flex-shrink-0 items-center gap-2">
                              {project.assigned_issues > 0 && (
                                <Tooltip tooltipContent="完成率" position="left" isMobile={isMobile}>
                                  <div
                                    className={`rounded-sm px-1 py-0.5 text-11 font-medium ${
                                      completedIssuePercentage <= 35
                                        ? "bg-danger-subtle text-danger-primary"
                                        : completedIssuePercentage <= 70
                                          ? "bg-yellow-500/10 text-yellow-500"
                                          : "bg-success-subtle text-success-primary"
                                    }`}
                                  >
                                    {completedIssuePercentage}%
                                  </div>
                                </Tooltip>
                              )}
                              <ChevronDownIcon className="h-4 w-4" />
                            </div>
                          </Disclosure.Button>
                          <Transition
                            show={open}
                            enter="transition duration-100 ease-out"
                            enterFrom="transform opacity-0"
                            enterTo="transform opacity-100"
                            leave="transition duration-75 ease-out"
                            leaveFrom="transform opacity-100"
                            leaveTo="transform opacity-0"
                          >
                            <Disclosure.Panel className="mt-3 pl-9">
                              <div
                                className="h-1.5 overflow-hidden rounded-full bg-layer-2"
                                role="progressbar"
                                aria-label="负责工作项完成率"
                                aria-valuenow={completedIssuePercentage}
                                aria-valuemin={0}
                                aria-valuemax={100}
                              >
                                <div
                                  className="bg-success-solid h-full rounded-full"
                                  style={{ width: `${completedIssuePercentage}%` }}
                                />
                              </div>
                              <div className="mt-3 space-y-1 text-12 text-secondary">
                                {[
                                  {
                                    label: "创建",
                                    count: project.created_issues,
                                    view: "created",
                                    filters: {},
                                    color: "#203b80",
                                  },
                                  {
                                    label: "负责",
                                    count: project.assigned_issues,
                                    view: "assigned",
                                    filters: {},
                                    color: "#3f76ff",
                                  },
                                  {
                                    label: "待处理",
                                    count: project.pending_issues,
                                    view: "assigned",
                                    filters: { pending: "1" },
                                    color: "#f59e0b",
                                  },
                                  {
                                    label: "已完成",
                                    count: project.completed_issues,
                                    view: "assigned",
                                    filters: { state_group: "completed" },
                                    color: "#16a34a",
                                  },
                                ].map((metric) => (
                                  <Link
                                    key={metric.label}
                                    href={profileWorkItemsHref(workspaceSlug, userId, metric.view, {
                                      project_id: project.id,
                                      ...metric.filters,
                                    })}
                                    className="flex items-center justify-between gap-2 rounded px-1 py-1.5 hover:bg-layer-1 hover:text-accent-primary"
                                  >
                                    <span className="flex items-center gap-2">
                                      <span className="size-2 rounded-sm" style={{ backgroundColor: metric.color }} />
                                      {metric.label}
                                    </span>
                                    <span className="shrink-0 font-medium tabular-nums">{metric.count} 项</span>
                                  </Link>
                                ))}
                              </div>
                            </Disclosure.Panel>
                          </Transition>
                        </div>
                      )}
                    </Disclosure>
                  );
                })}
              </div>
            </div>
          </>
        ) : (
          <Loader className="space-y-7 px-5">
            <Loader.Item height="130px" />
            <div className="space-y-5">
              <Loader.Item height="20px" />
              <Loader.Item height="20px" />
              <Loader.Item height="20px" />
              <Loader.Item height="20px" />
              <Loader.Item height="20px" />
            </div>
          </Loader>
        )}
      </div>
    </aside>
  );
});
