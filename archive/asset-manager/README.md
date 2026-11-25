# Legacy asset_manager archive

This directory preserves the non-duplicate metadata and orphan files from the
local `011/asset_manager` workspace before that 5.6 GB folder was removed.

## Canonical indexes

- `../../model-telegram-index.json`: 39 model entries + 7 effect-model bundle
  parts.
- `../../asset-telegram-index.json`: 4,717 non-model Telegram asset entries
  across templates, text effects, bubbles, animations, audio, fonts,
  dependencies, handwrite and text glow.

Chat IDs and local absolute paths are intentionally excluded from both
canonical indexes.

## Contents

- `metadata/`: runtime catalogs/dumps, text-template manifests, generation
  manifests, runtime evidence and source documentation.
- `indexes-sanitized/`: copies of the original Telegram indexes with
  `chat_id`/`chatId`, `next_update_id` and local absolute paths removed.
- `tools/`: asset generation and Telegram collection scripts.
- `orphans/`: the 77 local files that were not represented by an existing
  Telegram ID, preview index, demo repository or clean app asset. Every file
  is recorded in `ORPHAN-MANIFEST.tsv` with byte count and SHA-256.

## Pending artifact

`orphans/demo-upload/text-templates/assets/7687939821905513736.zip` was not
uploaded because the Telegram bot was blocked:

- bytes: 1,341,208
- SHA-256:
  `76abd2511bee9390e19b7cb4029e144fb5a3ce85059535fa48ae97b8983107e2`

It remains preserved here and is represented in `asset-telegram-index.json`
with `status: pending-git-archive`.

## Coverage rules

- Effect-model ZIP/parts are omitted from `orphans`: they are already present
  as seven verified Telegram parts in `model-telegram-index.json`.
- The 18 text-template dependency ZIPs are omitted: each matched the recorded
  `fileHash`, byte count, SHA-256 and Telegram file ID.
- Preview/cover files covered by `msc011_file` preview indexes or the current
  demo/clean app assets are not duplicated here.
