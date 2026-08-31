import type { ResourceItem } from "../../lib/types";

/** Only the dedicated interactive-audio document supports playback questions. */
export function isInteractiveAudioResource(
  resource: Pick<ResourceItem, "kind" | "payload">,
): boolean {
  return resource.kind === "doc" && resource.payload?.template === "interactive_audio";
}
