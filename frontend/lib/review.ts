export function formatReviewTime(value?: string | null): string {
  if (!value) return "尚未安排";
  return new Date(value).toLocaleString("zh-CN", {
    month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

// Keep observed assistance across card navigation, remounts and page reloads.
// A successful submission clears only that card's current revision.
const localHelp = new Set<string>();
function helpFlag(key: string, value?: boolean): boolean {
  if (value !== undefined) {
    if (value) localHelp.add(key); else localHelp.delete(key);
    try { if (value) sessionStorage.setItem(key, "1"); else sessionStorage.removeItem(key); } catch { /* memory fallback */ }
  }
  try { return localHelp.has(key) || sessionStorage.getItem(key) === "1"; } catch { return localHelp.has(key); }
}
export function recallHelp(resource: string, card: string, revision: number, value?: boolean): boolean {
  return helpFlag(`recall-help:${resource}:${card}:${revision}`, value);
}
export function markRecallLyricsHelp(resource: string) { helpFlag(`recall-lyrics:${resource}`, true); }
export function takeRecallLyricsHelp(resource: string): boolean {
  const key = `recall-lyrics:${resource}`;
  const seen = helpFlag(key);
  if (seen) helpFlag(key, false);
  return seen;
}
