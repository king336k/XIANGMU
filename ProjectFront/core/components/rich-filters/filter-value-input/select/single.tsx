/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useTranslation } from "@plane/i18n";
import React, { useState, useEffect } from "react";
import { observer } from "mobx-react";
// plane imports
import type {
  IFilterOption,
  TFilterProperty,
  TSingleSelectFilterFieldConfig,
  TFilterConditionNodeForDisplay,
} from "@plane/types";
import { CustomSearchSelect } from "@plane/ui";
// local imports
import { SelectedOptionsDisplay } from "./selected-options-display";
import { getCommonCustomSearchSelectProps, getFormattedOptions, loadOptions } from "./shared";

type TSingleSelectFilterValueInputProps<P extends TFilterProperty> = {
  config: TSingleSelectFilterFieldConfig<string>;
  condition: TFilterConditionNodeForDisplay<P, string>;
  isDisabled?: boolean;
  onChange: (value: string | null) => void;
};

export const SingleSelectFilterValueInput = observer(function SingleSelectFilterValueInput<P extends TFilterProperty>(
  props: TSingleSelectFilterValueInputProps<P>
) {
  const { t } = useTranslation();
  const { config, condition, onChange, isDisabled } = props;
  // states
  const [options, setOptions] = useState<IFilterOption<string>[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  // derived values
  const displayOptions = options.map((option) => ({
    ...option,
    label:
      condition.property === "priority"
        ? t(option.value)
        : condition.property === "state_group"
          ? t(`filters_workspace.state_groups.${option.value}`)
          : option.label,
  }));
  const formattedOptions = getFormattedOptions<string>(displayOptions);

  useEffect(() => {
    loadOptions({ config, setOptions, setLoading });
  }, [config]);

  const handleSelectChange = (value: string) => {
    if (value === condition.value) {
      onChange(null);
    } else {
      onChange(value);
    }
  };

  return (
    <CustomSearchSelect
      {...getCommonCustomSearchSelectProps(isDisabled)}
      value={condition.value}
      onChange={handleSelectChange}
      options={formattedOptions}
      multiple={false}
      disabled={loading || isDisabled}
      customButton={
        <SelectedOptionsDisplay<string> selectedValue={condition.value} options={displayOptions} displayCount={1} />
      }
      defaultOpen={!condition.value}
    />
  );
});
