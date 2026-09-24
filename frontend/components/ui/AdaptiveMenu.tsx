"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { MoreHorizontal } from "lucide-react";

export default function AdaptiveMenu({ label, className = "", children, expandedAt = 1400, icon, guide }: { label: string; className?: string; children: ReactNode; expandedAt?: number; icon?: ReactNode; guide?: string }) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const media = window.matchMedia(`(min-width: ${expandedAt}px)`);
    const update = () => { if (ref.current) ref.current.open = media.matches; };
    update();
    media.addEventListener("change", update);
    const outside = (event: PointerEvent) => {
      if (!media.matches && ref.current && !ref.current.contains(event.target as Node)) ref.current.open = false;
    };
    document.addEventListener("pointerdown", outside);
    return () => { media.removeEventListener("change", update); document.removeEventListener("pointerdown", outside); };
  }, [expandedAt]);
  return <details ref={ref} className={`adaptive-menu ${className}`} onKeyDown={event => {
    if (event.key === "Escape" && window.innerWidth < expandedAt && ref.current) { ref.current.open = false; ref.current.querySelector("summary")?.focus(); }
  }}>
    <summary className="study-icon" aria-label={label} title={label} data-guide={guide}>{icon || <MoreHorizontal size={21} />}</summary>
    <div className="adaptive-menu-content" onClick={event => {
      if ((event.target as HTMLElement).closest("button") && window.innerWidth < expandedAt && ref.current) {
        ref.current.open = false;
        ref.current.querySelector("summary")?.focus();
      }
    }}>{children}</div>
  </details>;
}
