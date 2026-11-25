# Demo upload set

This folder contains only the small Telegram demo set. Full previews remain in
Git; full asset archives remain under `asset-vault/`.

Rules:

- Maximum 10 assets per type in the first Telegram pass.
- Each type gets its own subdirectory and manifest.
- The app reads the full Git catalog, not this folder directly.

Current set:

- `fonts/`: 10 real TTF/OTF files with full Git previews.
- `text-animations/`: 10 diverse In/Out/Loop demo ZIPs.
- `text-effects/`: 10 diverse effect ZIPs.
- `text-bubbles/`: 10 bubble ZIPs.
- `text-templates/`: 10 template ZIPs + runtime dependencies.
- `handwrite/`: runtime brush closure.
- `text-glow/`: real bloom closure.

Each type has its own `manifest.json`; the aggregate index is
`demo-upload/manifest.json`.
