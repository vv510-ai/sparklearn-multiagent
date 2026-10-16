"use client";

/**
 * Local aurora backdrop. It replaces the former remote CloudFront video so the
 * login and loading screens render instantly, work offline (for example at a
 * competition venue) and never depend on a third-party CDN.
 */
export default function CinematicBackground({ subdued = false, light = false }: { subdued?: boolean; light?: boolean }) {
  return (
    <div className={`ll-aurora ${light ? "is-light" : ""}`} aria-hidden style={subdued ? { filter: "saturate(0.9)" } : undefined}>
      <i />
      <i />
      <i />
      <i />
      {!light && <span className="ll-grid" />}
    </div>
  );
}
