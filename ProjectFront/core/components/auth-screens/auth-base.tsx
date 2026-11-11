/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React from "react";
import { AuthRoot } from "@/components/account/auth-forms/auth-root";
import { EAuthModes } from "@/helpers/authentication.helper";
import { AuthFooter } from "./footer";
import { AuthHeader } from "./header";

type AuthBaseProps = {
  authType: EAuthModes;
};

export function AuthBase({ authType }: AuthBaseProps) {
  if (authType === EAuthModes.SIGN_IN)
    return (
      <main className="relative flex min-h-dvh w-full items-center justify-center overflow-y-auto bg-[#f1f7f4] px-5 py-10 dark:bg-[#111c1a]">
        <AuthRoot authMode={authType} />
      </main>
    );
  return (
    <div className="relative z-10 flex h-screen w-screen flex-col items-center overflow-hidden overflow-y-auto px-8 pt-6 pb-10">
      <AuthHeader type={authType} />
      <AuthRoot authMode={authType} />
      {authType === EAuthModes.SIGN_UP && <AuthFooter />}
    </div>
  );
}
