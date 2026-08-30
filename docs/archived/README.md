# Archived support material

Files here backed decisions that are already made and recorded in the design
document's decision log (`docs/design/architecture-v1-2026-08-18.md`, section 13).
They are kept for reference only; nothing current depends on them.

- `spikes/6a-delivery/`: the delivery-mechanism spike behind the D-spike and D14
  decisions (channels, Stop hook, resume). The Stop hook remains the recorded
  fallback if the wake-at-turn-end check fails during v1 acceptance; after that
  check passes, this directory can be deleted.
- `ui-designs/`: the static WebUI prototypes behind D18, superseded by `webui/`.