// SPDX-License-Identifier: AGPL-3.0-only
import logo from "@/app/assets/brand/engram-logo.png?url";
import lightLogo from "@/app/assets/brand/engram-logo-light.png?url";
import symbol from "@/app/assets/brand/engram-symbol.png?url";

export function PlatformLogo({ className = "h-9 w-auto", compact = false }: { className?: string; compact?: boolean }) {
  if (compact) return <img src={symbol} alt="忆生科技 TranscEngram" className={`object-contain ${className}`} />;
  return (
    <span className={`inline-flex ${className}`}>
      <img
        src={lightLogo}
        alt="忆生科技 TranscEngram"
        className="h-full w-auto max-w-full object-contain dark:hidden"
      />
      <img
        src={logo}
        alt="忆生科技 TranscEngram"
        className="hidden h-full w-auto max-w-full object-contain dark:block"
      />
    </span>
  );
}
