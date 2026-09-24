"use client";

import { createContext, useEffect } from "react";

export const LearnerScope = createContext("");
export const STUDY_DRAFT_EVENT = "learnloop:study-draft";

export function readStudyDraft<T>(key: string, valid: (value: unknown) => value is T): T | null {
  try {
    const saved = JSON.parse(localStorage.getItem(key) || "null");
    if (saved?.version === 1 && Date.now() - saved.updatedAt < 30 * 86400_000 && valid(saved.value)) return saved.value;
  } catch { /* Storage is optional, including in private browsing. */ }
  return null;
}

export function writeStudyDraft(key: string, value: unknown, source = "") {
  try {
    localStorage.setItem(key, JSON.stringify({ version: 1, updatedAt: Date.now(), value }));
    window.dispatchEvent(new CustomEvent(STUDY_DRAFT_EVENT, { detail: { key, source } }));
  }
  catch { /* Keep the current in-memory answer when storage is unavailable. */ }
}

export function useStudyViewport() {
  useEffect(() => {
    const viewport = window.visualViewport;
    const root = document.documentElement;
    let frame = 0;
    let fullHeight = window.innerHeight;
    let lastWidth = window.innerWidth;
    const update = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        // Pinch zoom must keep native panning instead of shrinking the workspace.
        if (viewport && Math.abs(viewport.scale - 1) > 0.05) return;
        const height = viewport?.height || window.innerHeight;
        if (Math.abs(window.innerWidth - lastWidth) > 80) fullHeight = window.innerHeight;
        lastWidth = window.innerWidth;
        fullHeight = Math.max(fullHeight, window.innerHeight);
        const editing = document.activeElement?.matches("textarea, input:not([type=checkbox]):not([type=radio])");
        const keyboard = Boolean(editing && fullHeight - height > 120);
        root.style.setProperty("--study-viewport-height", `${height}px`);
        root.style.setProperty("--study-viewport-top", `${viewport?.offsetTop || 0}px`);
        root.dataset.studyKeyboard = String(keyboard);
      });
    };
    update();
    viewport?.addEventListener("resize", update);
    viewport?.addEventListener("scroll", update);
    window.addEventListener("resize", update);
    document.addEventListener("focusin", update);
    document.addEventListener("focusout", update);
    return () => {
      cancelAnimationFrame(frame);
      viewport?.removeEventListener("resize", update);
      viewport?.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
      document.removeEventListener("focusin", update);
      document.removeEventListener("focusout", update);
      root.style.removeProperty("--study-viewport-height");
      root.style.removeProperty("--study-viewport-top");
      delete root.dataset.studyKeyboard;
    };
  }, []);
}
