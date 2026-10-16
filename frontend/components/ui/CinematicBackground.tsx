"use client";

/**
 * Local aurora backdrop. It replaces the former remote CloudFront video so the
 * login and loading screens render instantly, work offline (for example at a
 * competition venue) and never depend on a third-party CDN.
 */
export default function CinematicBackground({ subdued = false, light = false, video = false }: { subdued?: boolean; light?: boolean; video?: boolean }) {
  // Keep the original cinematic login while the learning workspace uses the local backdrop.
  if (video) {
    return (
      <div className="cinematic-background" aria-hidden>
        <video
          src="https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260314_131748_f2ca2a28-fed7-44c8-b9a9-bd9acdd5ec31.mp4"
          autoPlay loop muted playsInline preload="auto"
          className={`cinematic-video ${subdued ? "cinematic-video--subdued" : ""}`}
        />
      </div>
    );
  }
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
