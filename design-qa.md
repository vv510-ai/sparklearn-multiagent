# LearnLoop Conversation-First Design QA

Date: 2026-09-24. Scope: the approved combined concept in the existing learning application. Local verification only, not a production release.

The previous transition review is preserved unchanged in `docs/design-qa-workspace-transition.md`.

## Visual Evidence

- Source visual truth: `C:/Users/26054/.codex/generated_images/01a0cf34-0339-7110-a483-af52c2158f52/exec-cb142e69-9377-43b1-b628-3e29593d0a9b.png`.
- Reference copy: `.tmp/conversation-first-delivery/reference.png`.
- Implementation: `.tmp/conversation-first-delivery/phone.png`.
- Same-input comparison: `.tmp/conversation-first-delivery/comparison.png`.
- Additional captures: `.tmp/conversation-first-delivery/tablet.png`, `desktop.png`, `expanded-input.png`, `focused-answer.png`.
- Source pixels: 853 x 1844. Implementation pixels and CSS viewport: 390 x 844, deviceScaleFactor 1. In the comparison, the source is rendered 390 pixels wide preserving aspect ratio (843.1 pixels high); implementation remains 390 x 844. No device/browser frame is included.
- State: authenticated, one selected source, completed affect/effect conversation, collapsed citation, empty composer, keyboard closed. The implementation uses ordinary Markdown, not a hard-coded vocabulary component.
- Both images were inspected in one browser-rendered comparison. At this size labels and controls are readable; separate crops were unnecessary. Full-resolution tablet, desktop, expanded-input and practice captures were also opened.

## Findings And Comparison History

1. Initial capture: [P2] a closed evidence panel cast its shadow onto the chat. Fixed with visibility and inert state; the final comparison has an unobstructed white surface.
2. Initial 320 x 740 check: [P2] excess textarea minimum height reduced reading space below the 68% target. Corrected to 56 pixels while preserving two lines and 44-pixel controls. Final compact-view tests pass.
3. Initial source interaction: [P2] the last selected source could not be deselected. Empty selection is now permitted; the context row disappears in automatic mode, while strict mode remains visible. Tests also verify the outgoing empty source list and strict policy.
4. Post-fix comparison: no remaining actionable P0/P1/P2 findings in scope. Header, source context, reading area, citation, action row and full-width composer follow the accepted hierarchy.

## Required Fidelity Surfaces

- Fonts/typography: 16-pixel body and input, Chinese/system sans-serif fallbacks, zero letter spacing. Semantic Markdown is retained; the mock's oversized colored headwords and numbered circles are intentionally not hard-coded into arbitrary model answers.
- Spacing/layout: one 56-pixel compact header, optional 44-pixel source row, no duplicate chat heading or permanent bottom navigation. The source row is deliberately taller than the mock's approximate 32 pixels for touch access. Textarea owns its full row; tablet/desktop retain collapsible side panes.
- Colors/tokens: white workspace, gray user messages, green `#176c58` actions, blue `#326ec4` citations. Send is gray while empty, unlike the mock's always-green illustration. Hidden panels no longer tint the page.
- Images/icons: existing LearnLoop brand mark retained; new controls use the existing Lucide library. This text-based sample requires no new raster teaching assets. Source text is selectable, not a flattened screenshot.
- Copy/content: live course/source data, visible strict-source boundary, expandable citation disclaimer and original excerpts, concise empty-state learning actions. No explanatory styling copy was added to the app.

## Verification

- `npm run build`: passed. `npm run typecheck`: passed.
- Chromium on local production-mode Next.js with an isolated Demo backend: 31 tests passed (4 new cases plus 27 regressions).
- New visual matrix: 320x740, 360x800, 390x844, 430x932, 768x1024, 1024x768, 1440x900, 1920x1080, 640x420. Existing responsive tests additionally cover 900x720 and 1280x800.
- Verified: no viewport overflow, visible input/send, source selection and strict request contract, source/tool dialogs and focus return, copy, quiz generation request, new conversation, long labels, enlarged root font, drafts, touch Enter, Chinese composition, failed-send recovery, simulated VisualViewport, assessment scroll, quiz hints/report, account isolation, formula overflow and citation isolation.
- The new visual test captures console errors and uncaught page errors: none observed. Other regression scenarios intentionally simulate failed requests where documented.
- Vocabulary answers and source metadata in the new visual test are explicit transport fixtures. Authentication, notebook creation/reset use the local backend. Quiz regressions also exercise persistence, hints and evaluation. This does not establish real model quality.

## Residual Coverage

- P3: exact typeface rasterization, icon variants and vocabulary styling differ from the generated mock; reusable semantic content and readable text take priority.
- Not verified: physical iOS Safari, Android keyboards/candidate bars, WeChat, OS text scaling, production model and live release. Browser simulations are not device tests.
- No backend implementation changed; the historical 463-test backend result is not a fresh result for this iteration.
- Publication has not occurred.

## Checklist

- [x] Approved concept applied to the existing app.
- [x] Redundant chrome removed; tools, source boundaries and drafts retained.
- [x] Actual mobile/tablet/desktop captures inspected against the source.
- [x] Build, typecheck and 31 browser tests passed.
- [x] Mock/live and local/production boundaries stated.

final result: passed
