"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Compass } from "lucide-react";
import type { Driver } from "driver.js";

/** One short introduction per account/browser. Explicit help always replays it. */
export default function LearningGuide({ userId, enabled, onPrepare }: {
  userId: string; enabled: boolean; onPrepare: () => void;
}) {
  const tour = useRef<Driver | null>(null);
  const starting = useRef(false);
  const mounted = useRef(true);
  const prepare = useRef(onPrepare);
  prepare.current = onPrepare;
  const [error, setError] = useState("");
  const key = `learnloop:welcome-guide:v1:${userId}`;
  const start = useCallback(async () => {
    if (starting.current || tour.current?.isActive()) return;
    starting.current = true;
    setError("");
    prepare.current();
    try {
      const { driver } = await import("driver.js");
      // Let the chat pane render before resolving anchors.
      await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
      if (!mounted.current) return;
      const sourcesVisible = !!document.querySelector("[data-guide='sources']")?.getBoundingClientRect().width;
      const studioVisible = !!document.querySelector("[data-guide='studio']")?.getBoundingClientRect().width;
      const previousFocus = document.activeElement as HTMLElement | null;
      tour.current = driver({
        animate: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
        smoothScroll: false, overlayOpacity: 0.22, stagePadding: 8, stageRadius: 14,
        popoverClass: "learnloop-tour", showProgress: true,
        progressText: "{{current}} / {{total}}", nextBtnText: "下一步", prevBtnText: "上一步", doneBtnText: "开始学习",
        allowClose: true, overlayClickBehavior: "close",
        onPopoverRender: popover => { popover.closeButton.setAttribute("aria-label", "跳过引导"); },
        onDestroyed: () => {
          try { localStorage.setItem(key, "seen"); } catch { /* Private browsing may block storage. */ }
          tour.current = null;
          if (previousFocus?.isConnected && previousFocus !== document.body) previousFocus.focus();
        },
        steps: [
          { element: "#learning-chat-input", popover: { title: "从你卡住的地方开始", description: "直接说想学什么、哪里没懂。小知会根据问题和资料安排回答，你只需要专注学习。", side: "top", align: "start" } },
          { element: sourcesVisible ? "[data-guide='sources']" : "[data-guide='sources-nav']", popover: { title: "有自己的资料，就带进来", description: "选择一门课程，或上传讲义。选中的资料会成为这次学习的依据。", side: sourcesVisible ? "right" : "bottom", align: "start" } },
          { element: studioVisible ? "[data-guide='studio']" : "[data-guide='studio-nav']", popover: { title: "学过以后，试着用一次", description: "笔记、导图、测验和其他功能都在学习工坊。小知也会随学习进度建议下一步，随时可以跳过。", side: studioVisible ? "left" : "top", align: "start" } },
        ],
      });
      tour.current.drive();
    } catch { if (mounted.current) setError("引导暂时未加载，点击可重试"); }
    finally { starting.current = false; }
  }, [key]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; tour.current?.destroy(); };
  }, []);
  useEffect(() => {
    if (!enabled) return;
    try { if (localStorage.getItem(key)) return; } catch { return; }
    const timer = window.setTimeout(() => {
      const input = document.getElementById("learning-chat-input") as HTMLTextAreaElement | null;
      if (input?.value.trim()) { try { localStorage.setItem(key, "seen"); } catch {} return; }
      void start();
    }, 650);
    return () => window.clearTimeout(timer);
  }, [enabled, key, start]);
  return <button type="button" onClick={() => void start()} className="notebook-icon-button" aria-label="学习指引" title={error || "学习指引：随时重新查看"}><Compass size={18} /></button>;
}
