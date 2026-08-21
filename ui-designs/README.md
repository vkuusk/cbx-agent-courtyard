# UI design prototypes

Static, throwaway layout prototypes for step 7 (WebUI quickstart UX). **Frontend only** —
no hub, no API, no build step. Open a file in a browser and click around:

```
open ui-designs/mainboard.html
```

Each prototype is one self-contained HTML file (styles and fake data inline) so it renders
from `file://` with nothing running. The design tokens are copied from `webui/style.css`, so
an approved layout translates to the real app mechanically.

Every prototype carries a **prototype-only** bar at the top for switching between states
(first run, running, trouble). That bar is scaffolding for review — it is not part of the
design and does not get implemented.

| File | Step | Covers |
|---|---|---|
| `mainboard.html` | 7a | MainBoard: team strip, Needs you / Quiet grouping, inline gate decisions, delivery health, inactive fold |

Nothing here is wired to `webui/`. When a layout is approved it is implemented there and the
prototype stops being the source of truth.
