# UI redesign audit

Scope: interface only. Retain hash routes, original action handlers, request
payloads, credentials, saved rules, cache, backups, and all Python business logic.

| Page | Audit finding | Presentation change |
| --- | --- | --- |
| Overview | Repeated onboarding blocks compete with stats; activity is far below actions | A concise welcome action, metrics, quota, and collapsible setup guidance; activity shortcut in the header |
| Videos | Filters consume a full card; selection has little context; mobile table requires scrolling | Compact search toolbar, Filters dialog, visible selected count, scrollable table with clear empty action |
| Bulk Edit | Help and repeated scanning buttons dominate; advanced rule controls compete with the main fields | Single focused editor, contextual help dialog, collapsed rule options, separate preview/review stage |
| Links | Long URL lists feel unstructured | Domain sections, clear count badges, consistent link rows and empty action |
| Download | Large toolchain card plus long options makes the starting point unclear | URL + presets first; configuration and environment details moved into a dialog with tabs; keep every option |
| Tools | Cookie configuration competes with exports; two permanent export buttons | Purposeful utility cards, an export format dialog, focused cookie settings dialog |
| Help | Dense cards compete equally | Scannable sections and short troubleshooting disclosures |

Global changes: neutral surfaces, blue action color, system font, compact header,
sidebar navigation, mobile Sheet, command navigation, theme dropdown, focused
Dialog/AlertDialog flows, consistent feedback with Sonner, keyboard focus,
reduced-motion support, and light/dark tokens.

Implementation: shadcn/ui components are source-owned under `frontend/components/ui`.
Static shadcn form/card components are rendered into the HTML at build time to
retain native DOM IDs and the existing app.js controllers. Interactive navigation,
dialogs, sheets, dropdowns, command search, and toasts run in React. Existing DOM
form nodes move into focused dialogs without cloning or discarding their state.
The Python app serves the compiled frontend; Node is only needed to rebuild it.

The revised visual direction uses the local Link Sans variable font, the red
brand mark, a Linktree-inspired creator-studio desktop workspace that uses the
full available canvas, and a mobile tab
bar. The original brand font asset is served locally without a font service.

Destructive rule removal uses AlertDialog. Publishing retains the exact UPDATE
confirmation and reviewed preview token. Moving fields into dialogs keeps the
original elements, IDs, listeners, selected values and controller payloads.
The UI build has no credentials, API clients, or remote font dependencies.

## Verification

- TypeScript check, production build, and JavaScript syntax check passed.
- Seven backend preview-safety tests and 18 replacement-engine self-tests passed.
- Offline Chrome tests cover all seven pages at 375, 768, 812, 1024, 1440, and
  1920 pixels, including landscape mobile and portrait tablet layouts.
- Mocked scan, stop, sync, export, thumbnails, download preview/format/start and
  reviewed-token Apply requests preserve their original payloads. No live calls.
- Dialog field persistence, every download preset and settings tab, rule removal
  confirmation, UPDATE gating, selection changes, appearance menu, command search,
  mobile navigation, focus restoration/trapping, and reduced motion are checked.
- Axe WCAG A/AA checks pass on all seven pages in both themes and on every
  download-settings tab. Screenshots are in `.ui-preview/` (ignored local output).

Limitations: browser verification used desktop Chrome with emulated viewports;
Safari, Firefox, real mobile devices and live Google/YouTube flows were not tested.
Backup restoration remains the existing manual process. Dialog settings retain
their current-session values; this redesign does not change persistence rules.
