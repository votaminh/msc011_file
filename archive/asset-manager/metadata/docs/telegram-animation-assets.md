# Telegram text-animation asset index

The helper stores Telegram file IDs instead of uploading the same ZIP on every
download.

## One-time bot setup

1. Send `/start` to the bot from the destination account or add the bot to the
   destination group.
2. Resolve the chat ID:

```bash
export TELEGRAM_BOT_TOKEN='...'
python3 tools/telegram/text_animation_assets.py chat-id
```

Do not commit the token.

## Verify the local source bundle

The full directory has 530 ZIPs. Ten ZIPs were previously copied into the app
as an offline fallback, but the app no longer bundles any animation asset.
Those ten files must exist in the external source bundle or be recovered from
the existing Telegram index before rebuilding a complete local mirror.

```bash
python3 tools/telegram/text_animation_assets.py verify \
  --catalog '/Users/votaminh99/Documents/Default Project/demo_andorid/text_animations_full/catalog.full.json' \
  --asset-dir '/Users/votaminh99/Documents/Default Project/demo_andorid/text_animations_full'
```

The source mirror can report `missing=10` after the app fallback was removed.
The production source of those ten assets is now Telegram; use the saved
`fileId` index to download them.

## Upload once and build the file-index JSON

```bash
export TELEGRAM_BOT_TOKEN='...'
export TELEGRAM_CHAT_ID='...'
python3 tools/telegram/text_animation_assets.py upload \
  --catalog '/Users/votaminh99/Documents/Default Project/demo_andorid/text_animations_full/catalog.full.json' \
  --asset-dir '/Users/votaminh99/Documents/Default Project/demo_andorid/text_animations_full' \
  --index tools/telegram/text-animations-telegram-index.json
```

The index is updated atomically after each successful upload and can be resumed.

## Scan files uploaded manually

If the files are uploaded to the bot by the user instead of this script, scan
the bot updates and build/merge the same `file_id` index:

```bash
export TELEGRAM_BOT_TOKEN='...'
python3 tools/telegram/text_animation_assets.py scan \
  --catalog '/Users/votaminh99/Documents/Default Project/demo_andorid/text_animations_full/catalog.full.json' \
  --asset-dir '/Users/votaminh99/Documents/Default Project/demo_andorid/text_animations_full' \
  --index tools/telegram/text-animations-telegram-index.json
```

The scanner consumes Telegram updates in batches, maps filenames such as
`7646376969172471060.zip` back to catalog metadata, and stores
`next_update_id` so the next scan receives only newer files.

## Download from the saved index

```bash
export TELEGRAM_BOT_TOKEN='...'
python3 tools/telegram/text_animation_assets.py download \
  --index tools/telegram/text-animations-telegram-index.json \
  --output /tmp/text_animations_download
```

Download individual effects with `--effect-id <id>`.
