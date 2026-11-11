/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import type { IState, TStateOperationsCallbacks } from "@plane/types";
// components
import { StateForm } from "@/components/project-states";

type TStateUpdate = {
  state: IState;
  updateStateCallback: TStateOperationsCallbacks["updateState"];
  shouldTrackEvents: boolean;
  handleClose: () => void;
};

export const StateUpdate = observer(function StateUpdate(props: TStateUpdate) {
  const { state, updateStateCallback, handleClose } = props;
  // states
  const [loader, setLoader] = useState(false);

  const onCancel = () => {
    setLoader(false);
    handleClose();
  };

  const onSubmit = async (formData: Partial<IState>) => {
    if (!state.id) return { status: "error" };

    try {
      await updateStateCallback(state.id, formData);
      setToast({
        type: TOAST_TYPE.SUCCESS,
        title: "成功",
        message: "状态更新成功。",
      });
      handleClose();
      return { status: "success" };
    } catch (error) {
      const errorStatus = error as { status: number };
      if (errorStatus?.status === 400) {
        setToast({
          type: TOAST_TYPE.ERROR,
          title: "错误",
          message: "同名状态已存在，请使用其他名称。",
        });
        return { status: "already_exists" };
      } else {
        setToast({
          type: TOAST_TYPE.ERROR,
          title: "错误",
          message: "状态更新失败，请重试。",
        });
        return { status: "error" };
      }
    }
  };

  return (
    <StateForm
      data={state}
      onSubmit={onSubmit}
      onCancel={onCancel}
      buttonDisabled={loader}
      buttonTitle={loader ? "更新中" : "更新"}
    />
  );
});
