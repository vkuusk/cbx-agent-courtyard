# UI design prototypes

Static, throwaway layout prototypes for step 7 (WebUI quickstart UX). **Frontend only** —
no hub, no API, no build step. Open a file in a browser and click around:

```
open ui-designs/layout.html
```

Each prototype is one self-contained HTML file (styles and fake data inline) so it renders
from `file://` with nothing running. The design tokens are copied from `webui/style.css`, so
an approved layout translates to the real app mechanically.

Every prototype carries a **prototype-only** bar at the top for switching between states
(first run, running, trouble). That bar is scaffolding for review — it is not part of the
design and does not get implemented.

| File | Step | Covers |
|---|---|---|
| `layout.html` | 7 (overall layout) — **implemented in `webui/` 2026-08-22** | The app frame the pages live in: collapsible side bar (MainBoard · Agents on top, Admin at the bottom), agent rectangles as the team, lines drawn as two nodes + one colour-coded wire, a scrollable conversation pane, and the one operator input pinned to the bottom (target chosen by clicking an agent or a line). Supersedes the *layout* of `mainboard.html`. |
| `mainboard.html` | 7a | MainBoard, first pass (line cards): kept for its content ideas — inline gate decisions, delivery-health lines, inactive fold — which move into `layout.html`'s conversation pane and wires. |

Nothing here is wired to `webui/`. When a layout is approved it is implemented there and the
prototype stops being the source of truth.
