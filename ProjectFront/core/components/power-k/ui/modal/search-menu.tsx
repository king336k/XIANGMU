/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState, useEffect } from "react";
import useSWR from "swr";
import { Command } from "cmdk";
import { qualityApi } from "@/components/quality/api";
import { PowerKModalCommandItem } from "./command-item";
import { useParams } from "next/navigation";
// plane imports
import { WORKSPACE_DEFAULT_SEARCH_RESULT } from "@plane/constants";
import type { IWorkspaceSearchResults } from "@plane/types";
import { cn } from "@plane/utils";
// hooks
import { usePowerK } from "@/hooks/store/use-power-k";
import useDebounce from "@/hooks/use-debounce";
import { WorkspaceService } from "@/services/workspace.service";
// local imports
import type { TPowerKContext, TPowerKPageType } from "../../core/types";
import { PowerKModalNoSearchResultsCommand } from "./no-results-command";
import { PowerKModalSearchResults } from "./search-results";
// services init
const workspaceService = new WorkspaceService();

type Props = {
  activePage: TPowerKPageType | null;
  context: TPowerKContext;
  isWorkspaceLevel: boolean;
  searchTerm: string;
  updateSearchTerm: (value: string) => void;
  handleSearchMenuClose?: () => void;
};

export function PowerKModalSearchMenu(props: Props) {
  const { activePage, context, isWorkspaceLevel, searchTerm, updateSearchTerm, handleSearchMenuClose } = props;
  // states
  const [resultsCount, setResultsCount] = useState(0);
  const [isSearching, setIsSearching] = useState(false);
  const [results, setResults] = useState<IWorkspaceSearchResults>(WORKSPACE_DEFAULT_SEARCH_RESULT);
  const debouncedSearchTerm = useDebounce(searchTerm, 500);
  // navigation
  const { workspaceSlug, projectId } = useParams();
  const { data: numbered } = useSWR(
    workspaceSlug && /^[A-Za-z0-9_-]+-[A-Za-z]+-\d+$/.test(debouncedSearchTerm.trim())
      ? `/api/quality-auth/record-number/?workspace=${encodeURIComponent(String(workspaceSlug))}&code=${encodeURIComponent(debouncedSearchTerm.trim())}`
      : null,
    (url: string) =>
      qualityApi.read<{ results: { id: string; code: string; name: string; kind: string; url: string }[] }>(url)
  );
  // store hooks
  const { togglePowerKModal } = usePowerK();

  useEffect(() => {
    if (activePage || !workspaceSlug) return;
    setIsSearching(true);

    if (debouncedSearchTerm) {
      workspaceService
        .searchWorkspace(workspaceSlug.toString(), {
          ...(projectId ? { project_id: projectId.toString() } : {}),
          search: debouncedSearchTerm,
          workspace_search: !projectId ? true : isWorkspaceLevel,
        })
        // oxlint-disable-next-line no-shadow oxlint-disable-next-line promise/always-return
        .then((results) => {
          setResults(results);
          const count = Object.keys(results.results).reduce(
            (accumulator, key) => results.results[key as keyof typeof results.results]?.length + accumulator,
            0
          );
          setResultsCount(count);
        })
        .catch(() => {
          setResults(WORKSPACE_DEFAULT_SEARCH_RESULT);
          setResultsCount(0);
        })
        .finally(() => setIsSearching(false));
    } else {
      setResults(WORKSPACE_DEFAULT_SEARCH_RESULT);
      setIsSearching(false);
    }
  }, [debouncedSearchTerm, isWorkspaceLevel, projectId, workspaceSlug, activePage]);

  if (activePage) return null;

  const handleClosePalette = () => {
    handleSearchMenuClose?.();
    togglePowerKModal(false);
  };

  return (
    <>
      {searchTerm.trim() !== "" && (
        <div className="mt-4 flex items-center justify-between gap-2 px-4">
          <h5
            className={cn("text-11 text-primary", {
              "animate-pulse": isSearching,
            })}
          >
            {isWorkspaceLevel ? "工作空间" : "当前项目"}中搜索{" "}
            <span className="font-medium">
              {'"'}
              {searchTerm}
              {'"'}
            </span>{" "}
          </h5>
        </div>
      )}

      {/* Show empty state only when not loading and no results */}
      {!isSearching &&
        resultsCount === 0 &&
        !numbered?.results.length &&
        searchTerm.trim() !== "" &&
        debouncedSearchTerm.trim() !== "" && (
          <PowerKModalNoSearchResultsCommand
            context={context}
            searchTerm={searchTerm}
            updateSearchTerm={updateSearchTerm}
          />
        )}

      {!!numbered?.results.length && (
        <Command.Group heading="按编号找到的记录">
          {numbered.results.map((record) => (
            <PowerKModalCommandItem
              key={record.id}
              label={`${record.code} · ${record.name}`}
              value={`${record.code} ${record.name}`}
              onSelect={() => {
                handleClosePalette();
                context.router.push(record.url);
              }}
            />
          ))}
        </Command.Group>
      )}
      {searchTerm.trim() !== "" && <PowerKModalSearchResults closePalette={handleClosePalette} results={results} />}
    </>
  );
}
