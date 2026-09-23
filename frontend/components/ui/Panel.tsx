/** @jsxImportSource react */
﻿import type { ReactNode } from "react";

/**
 * Phase 0 · 基础面板与统一眉标头部。
 * 圆角规范:面板 rounded-xl / 内部块 rounded-lg / 徽章 rounded-md。
 * mono 眉标是全站唯一的"科技感"出口,统一 11px / 0.22em 字距,颜色只有三档:
 * info 松绿(默认)/ warn 橙(仅真正的警示面板)/ neutral 灰。
 */

export function Panel({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-[14px] border border-[#E5E9E3] bg-white shadow-[0_1px_2px_rgba(18,30,22,0.05),0_6px_20px_rgba(18,30,22,0.06)] ring-1 ring-[#182119]/[0.025] ${className}`}
    >
      {children}
    </section>
  );
}

type HeaderTone = "info" | "warn" | "neutral";
type HeaderSize = "sm" | "md" | "lg";

const CODE_TONE: Record<HeaderTone, string> = {
  info: "text-emerald-700",
  warn: "text-orange-600",
  neutral: "text-[#8B958D]",
};

const TITLE_SIZE: Record<HeaderSize, string> = {
  sm: "text-sm",
  md: "text-lg",
  lg: "text-2xl",
};

const DESC_SIZE: Record<HeaderSize, string> = {
  sm: "text-xs",
  md: "text-xs",
  lg: "text-sm",
};

export function PanelHeader({
  code,
  title,
  desc,
  right,
  tone = "info",
  size = "md",
}: {
  /** 面板眉标文本,如 "学习路线" */
  code: string;
  title?: ReactNode;
  desc?: ReactNode;
  /** 头部右侧插槽(图例、统计、按钮等) */
  right?: ReactNode;
  tone?: HeaderTone;
  size?: HeaderSize;
}) {
  return (
    <div className="flex flex-wrap items-start gap-3">
      <div className="min-w-0">
        <div className={`text-[11px] font-bold tracking-[0.18em] ${CODE_TONE[tone]}`}>
          {code}
        </div>
        {title != null && (
          <h2 className={`mt-1 font-bold tracking-tight text-[#182119] ${TITLE_SIZE[size]}`}>
            {title}
          </h2>
        )}
        {desc != null && <p className={`mt-1 leading-5 text-[#57635A] ${DESC_SIZE[size]}`}>{desc}</p>}
      </div>
      {right != null && <div className="ml-auto flex shrink-0 items-center gap-3">{right}</div>}
    </div>
  );
}

