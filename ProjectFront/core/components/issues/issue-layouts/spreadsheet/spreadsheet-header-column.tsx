/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useRef } from "react";
import type { IWorkItemFilterInstance } from "@plane/shared-state";
import { SPREADSHEET_PROPERTY_DETAILS } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { SpreadsheetColumnFilter } from "./spreadsheet-column-filter";
import { SPREADSHEET_COLUMN_FILTER_PROPERTIES } from "./spreadsheet-column-filter.helper";
//types
import { observer } from "mobx-react";
import type { IIssueDisplayFilterOptions, IIssueDisplayProperties } from "@plane/types";
//components
import { shouldRenderColumn } from "@/helpers/issue-filter.helper";
import { WithDisplayPropertiesHOC } from "../properties/with-display-properties-HOC";
import { HeaderColumn } from "./columns/header-column";

interface Props {
  filter?: IWorkItemFilterInstance;
  displayProperties: IIssueDisplayProperties;
  property: keyof IIssueDisplayProperties;
  isEstimateEnabled: boolean;
  displayFilters: IIssueDisplayFilterOptions;
  handleDisplayFilterUpdate: (data: Partial<IIssueDisplayFilterOptions>) => void;
  isEpic?: boolean;
}
export const SpreadsheetHeaderColumn = observer(function SpreadsheetHeaderColumn(props: Props) {
  const { displayProperties, displayFilters, property, handleDisplayFilterUpdate, filter, isEpic = false } = props;
  const { t } = useTranslation();
  const filterProperty = SPREADSHEET_COLUMN_FILTER_PROPERTIES[property];

  //hooks
  const tableHeaderCellRef = useRef<HTMLTableCellElement | null>(null);

  const shouldRenderProperty = shouldRenderColumn(property);

  return (
    <WithDisplayPropertiesHOC
      displayProperties={displayProperties}
      displayPropertyKey={property}
      shouldRenderProperty={() => shouldRenderProperty}
    >
      <th
        className="h-11 min-w-36 items-center border border-t-0 border-b-0 border-subtle bg-layer-1 py-1 text-13 font-medium"
        ref={tableHeaderCellRef}
        tabIndex={0}
      >
        <div className="flex items-center gap-1 px-2">
          <div className="min-w-0 flex-1">
            <HeaderColumn
              displayFilters={displayFilters}
              handleDisplayFilterUpdate={handleDisplayFilterUpdate}
              property={property}
              onClose={() => {
                tableHeaderCellRef?.current?.focus();
              }}
              isEpic={isEpic}
            />
          </div>
          {filter && filterProperty && (
            <SpreadsheetColumnFilter
              filter={filter}
              property={filterProperty}
              label={t(SPREADSHEET_PROPERTY_DETAILS[property]?.i18n_title || "work_items")}
            />
          )}
        </div>
      </th>
    </WithDisplayPropertiesHOC>
  );
});
