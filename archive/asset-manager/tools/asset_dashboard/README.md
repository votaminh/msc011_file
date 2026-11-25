# Asset Dashboard

Local-only dashboard for the CapCut asset vault.

## Double-click launcher

On macOS, double-click:

```text
tools/asset_dashboard/start.command
```

The launcher uses port `8765` when available, otherwise it scans up through
`8795`. It starts the server with the `asset-vault` in this `asset_manager`
directory and opens:

```text
http://127.0.0.1:8765/
```

The Terminal window stays open while the server is running. Closing that
window stops the server.

## Manual launch

```bash
python3 tools/asset_dashboard/server.py \
  --vault "$(pwd)/asset-vault" \
  --scan-on-start \
  --open
```

The server binds to `127.0.0.1:8765` and creates:

```text
asset-vault/
  objects/
  indexes/
    assets.json
    telegram-file-ids.json
  generated/
  staging/
  quarantine/
  cache/extracted/
```

`assets.json` is the canonical metadata index. Source files may remain external
until imported with the Add Asset dialog and `Copy into asset-vault/objects`
enabled.

The initial scan combines:

- 540 text animations from Git preview metadata / Telegram catalog
- 1.543 unique text effects
- 240 text bubbles
- 2.197 unique text templates
- 10 real font demo entries with full Git previews
- 63 downloaded CapCut effect-model files from the runtime cache
- video-effect metadata and local packs
- SegmentJS, curve text, style catalog and sample media
- Telegram `file_id`, size and hash from type-specific indexes

The current combined index is 5.655 assets, including 2.343 entries with a
Telegram file id. Select `Fonts` to inspect the real TTF/OTF preview generated
from the downloadable font file.
