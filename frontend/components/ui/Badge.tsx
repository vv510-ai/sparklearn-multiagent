/** @jsxImportSource react */
﻿import type { ReactNode } from "react";

export type BadgeVariant = "neutral" | "info" | "success" | "warn" | "danger";

const VARIANT: Record<BadgeVariant, string> = {
  neutral: "border-slate-200 bg-slate-50 text-slate-600",
  info: "border-emerald-200 bg-emerald-50 text-emerald-700",
  success: "border-emerald-200 bg-emerald-50 text-emerald-700",
  warn: "border-orange-200 bg-orange-50 text-orange-700",
  danger: "border-rose-200 bg-rose-50 text-rose-700",
};

/**
 * Phase 0 · 统一徽章。方角(rounded-md),取代散装 rounded-full 胶囊。
 * 语义:neutral 中性 / info 操作·推荐 / success 已掌握·完成 /
 *       warn 薄弱·待复核·错因 / danger 失败。
 */
export function Badge({
  variant = "neutral",
  mono = false,
  className = "",
  title,
  children,
}: {
  variant?: BadgeVariant;
  /** mono=true 用于 kind 代码等等宽文本(11px) */
  mono?: boolean;
  className?: string;
  /** 悬停提示(如状态说明) */
  title?: string;
  children: ReactNode;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 font-medium ${
        mono ? "font-mono text-[11px] tracking-wide" : "text-xs"
      } ${VARIANT[variant]} ${className}`}
    >
      {children}
    </span>
  );
}

