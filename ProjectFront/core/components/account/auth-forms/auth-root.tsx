/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import { useSearchParams } from "next/navigation";
// plane imports
import { OAuthOptions } from "@plane/ui";
// helpers
import type { TAuthErrorInfo } from "@/helpers/authentication.helper";
import {
  EAuthModes,
  EAuthSteps,
  EAuthenticationErrorCodes,
  EErrorAlertType,
  authErrorHandler,
} from "@/helpers/authentication.helper";
// hooks
import { useOAuthConfig } from "@/hooks/oauth";
import { useInstance } from "@/hooks/store/use-instance";
// local imports
import { TermsAndConditions } from "../terms-and-conditions";
import { AuthBanner } from "./auth-banner";
import { AuthHeader, AuthHeaderBase } from "./auth-header";
import { AuthFormRoot } from "./form-root";
import { PlatformLogo } from "@/components/common/platform-logo";
import { UsernameLoginForm } from "../username-login";

type TAuthRoot = {
  authMode: EAuthModes;
};

export const AuthRoot = observer(function AuthRoot(props: TAuthRoot) {
  //router
  const searchParams = useSearchParams();
  // query params
  const emailParam = searchParams.get("email");
  const invitation_id = searchParams.get("invitation_id");
  const workspaceSlug = searchParams.get("slug");
  const error_code = searchParams.get("error_code");
  // props
  const { authMode: currentAuthMode } = props;
  // states
  const [authMode, setAuthMode] = useState<EAuthModes | undefined>(undefined);
  const [authStep, setAuthStep] = useState<EAuthSteps>(EAuthSteps.EMAIL);
  const [email, setEmail] = useState(emailParam ? emailParam.toString() : "");
  const [errorInfo, setErrorInfo] = useState<TAuthErrorInfo | undefined>(undefined);
  // store hooks
  const { config } = useInstance();
  // derived values
  const oAuthActionText = authMode === EAuthModes.SIGN_UP ? "注册" : "登录";
  const { isOAuthEnabled, oAuthOptions } = useOAuthConfig(oAuthActionText);
  const isEmailBasedAuthEnabled = config?.is_email_password_enabled || config?.is_magic_login_enabled;
  const noAuthMethodsAvailable = !isOAuthEnabled && !isEmailBasedAuthEnabled;

  useEffect(() => {
    if (!authMode && currentAuthMode) setAuthMode(currentAuthMode);
  }, [currentAuthMode, authMode]);

  useEffect(() => {
    if (error_code && authMode) {
      const errorhandler = authErrorHandler(error_code?.toString() as EAuthenticationErrorCodes);
      if (errorhandler) {
        // password error handler
        if ([EAuthenticationErrorCodes.AUTHENTICATION_FAILED_SIGN_UP].includes(errorhandler.code)) {
          setAuthMode(EAuthModes.SIGN_UP);
          setAuthStep(EAuthSteps.PASSWORD);
        }
        if ([EAuthenticationErrorCodes.AUTHENTICATION_FAILED_SIGN_IN].includes(errorhandler.code)) {
          setAuthMode(EAuthModes.SIGN_IN);
          setAuthStep(EAuthSteps.PASSWORD);
        }
        // magic_code error handler
        if (
          [
            EAuthenticationErrorCodes.INVALID_MAGIC_CODE_SIGN_UP,
            EAuthenticationErrorCodes.INVALID_EMAIL_MAGIC_SIGN_UP,
            EAuthenticationErrorCodes.EXPIRED_MAGIC_CODE_SIGN_UP,
            EAuthenticationErrorCodes.EMAIL_CODE_ATTEMPT_EXHAUSTED_SIGN_UP,
          ].includes(errorhandler.code)
        ) {
          setAuthMode(EAuthModes.SIGN_UP);
          setAuthStep(EAuthSteps.UNIQUE_CODE);
        }
        if (
          [
            EAuthenticationErrorCodes.INVALID_MAGIC_CODE_SIGN_IN,
            EAuthenticationErrorCodes.INVALID_EMAIL_MAGIC_SIGN_IN,
            EAuthenticationErrorCodes.EXPIRED_MAGIC_CODE_SIGN_IN,
            EAuthenticationErrorCodes.EMAIL_CODE_ATTEMPT_EXHAUSTED_SIGN_IN,
          ].includes(errorhandler.code)
        ) {
          setAuthMode(EAuthModes.SIGN_IN);
          setAuthStep(EAuthSteps.UNIQUE_CODE);
        }

        setErrorInfo(errorhandler);
      }
    }
  }, [error_code, authMode]);

  if (!authMode) return <></>;

  if (authMode === EAuthModes.SIGN_IN)
    return (
      <section
        aria-label="登录项目管理平台"
        className="w-full max-w-[27rem] rounded-xl border border-[#d7e4df] bg-white/90 p-6 shadow-[0_8px_32px_rgba(0,0,0,0.06)] backdrop-blur-sm sm:p-8 dark:border-[#344d44] dark:bg-[#172824]"
      >
        <header className="mb-7 flex items-center gap-4">
          <PlatformLogo className="h-11 w-auto" />
          <div className="min-w-0 border-l border-[#d7e4df] pl-4 dark:border-[#344d44]">
            <h1 className="text-18 font-semibold text-primary">项目管理平台</h1>
            <p className="mt-1 text-12 text-secondary">账号登录</p>
          </div>
        </header>
        <UsernameLoginForm />
      </section>
    );

  if (authMode === EAuthModes.SIGN_UP)
    return (
      <AuthContainer>
        <AuthHeaderBase header="项目管理平台" subHeader="" />
        <p className="text-13 text-secondary">新用户由管理员创建。</p>
        <a href="/" className="mt-4 inline-block text-13 text-accent-primary">
          返回登录
        </a>
      </AuthContainer>
    );

  if (noAuthMethodsAvailable) {
    return (
      <AuthContainer>
        <AuthHeaderBase header="暂未启用登录方式" subHeader="请联系管理员配置登录方式。" />
      </AuthContainer>
    );
  }

  return (
    <AuthContainer>
      {errorInfo && errorInfo?.type === EErrorAlertType.BANNER_ALERT && (
        <AuthBanner message={errorInfo.message} handleBannerData={(value) => setErrorInfo(value)} />
      )}
      <AuthHeader
        workspaceSlug={workspaceSlug?.toString() || undefined}
        invitationId={invitation_id?.toString() || undefined}
        invitationEmail={email || undefined}
        authMode={authMode}
        currentAuthStep={authStep}
      />
      {isOAuthEnabled && (
        <OAuthOptions
          options={oAuthOptions}
          compact={authStep === EAuthSteps.PASSWORD}
          showDivider={isEmailBasedAuthEnabled}
        />
      )}
      {isEmailBasedAuthEnabled && (
        <AuthFormRoot
          authStep={authStep}
          authMode={authMode}
          email={email}
          setEmail={(email) => setEmail(email)}
          setAuthMode={(authMode) => setAuthMode(authMode)}
          setAuthStep={(authStep) => setAuthStep(authStep)}
          setErrorInfo={(errorInfo) => setErrorInfo(errorInfo)}
          currentAuthMode={currentAuthMode}
        />
      )}
      <TermsAndConditions authType={authMode} />
    </AuthContainer>
  );
});

function AuthContainer({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-10 flex w-full flex-grow flex-col items-center justify-center py-6">
      <div className="relative flex w-full max-w-[22.5rem] flex-col gap-6">{children}</div>
    </div>
  );
}
