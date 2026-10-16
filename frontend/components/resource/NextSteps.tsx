"use client";

import { ArrowRight, Compass } from "lucide-react";
import { nextStepsFor, type NextAction } from "@/lib/next-steps";
import type { ResourceItem } from "@/lib/types";

export default function NextSteps({ resource, disabled = false, onAction }: {
  resource: ResourceItem;
  disabled?: boolean;
  onAction: (action: NextAction) => void;
}) {
  const actions = nextStepsFor(resource);
  if (!actions.length) return null;
  return (
    <nav className="ll-next-steps" aria-label="下一步学习建议">
      <span><Compass size={15} aria-hidden />下一步</span>
      {actions.map(action => (
        <button key={`${action.type}-${action.label}`} type="button" disabled={disabled} onClick={() => onAction(action)}>
          {action.label}<small>· {action.reason}</small><ArrowRight size={13} aria-hidden />
        </button>
      ))}
    </nav>
  );
}
