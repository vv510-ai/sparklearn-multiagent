"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ArrowLeft } from "lucide-react";

export default function StudyDialog({ open, title, onClose, children, footer, className = "" }: {
  open: boolean; title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog || !open) return;
    const previous = document.activeElement as HTMLElement | null;
    dialog.showModal();
    return () => {
      dialog.close();
      if (previous?.isConnected) previous.focus({ preventScroll: true });
    };
  }, [mounted, open]);
  if (!mounted || !open) return null;
  return createPortal(<dialog ref={ref} className={`study-dialog ${className}`} aria-labelledby={titleId}
    onCancel={event => { event.preventDefault(); onClose(); }}>
    <header className="study-dialog-header">
      <button type="button" onClick={onClose} className="study-icon" aria-label="返回学习" title="返回学习"><ArrowLeft size={21} /></button>
      <h2 id={titleId}>{title}</h2>
    </header>
    <div className="study-dialog-body">{children}</div>
    {footer && <footer className="study-dialog-footer">{footer}</footer>}
  </dialog>, document.body);
}
