# Telegram Text Effects asset index

Text Effects dùng cùng mô hình với animation:

- ZIP gốc nằm trên Telegram;
- preview/thumbnail + metadata nằm trên Git;
- app tải ZIP theo click, không bundle asset trong APK.

## Kết quả hiện tại

- Runtime catalog: 23 category, 1.770 listing.
- Unique effect: 1.543.
- Telegram ZIP: 1.543/1.543, không failure.
- Tổng dung lượng ZIP: 1.484.696.120 byte.
- Public preview: 1.543 cover + 1.543 thumbnail + JSON.
- `text-effects-preview.json`: 1.770 item đều có `telegram.fileId`.

Commit public:

- `e66139a` — publish cover/thumb ban đầu.
- `5218880` — bổ sung đủ preview cho runtime cuối.
- `16b5811` — map toàn bộ Telegram `file_id`.

## Runtime dump

```bash
frida -D emulator-5556 -p <CapCut-PID> -q -t inf \
  -l tools/frida/dump-text-effects.js
```

Script autosave vào:

```text
/data/user/0/com.lemon.lvoverseas/files/text-effects-runtime.json
```

Pull về asset vault:

```bash
adb -s emulator-5556 pull \
  /data/user/0/com.lemon.lvoverseas/files/text-effects-runtime.json \
  "/Users/votaminh99/Documents/Default Project/demo_andorid/asset-vault/runtime/text-effects-runtime.json"
```

## Prefetch ZIP

```bash
python3 tools/telegram/text_effect_assets.py verify
python3 tools/telegram/text_effect_assets.py prefetch --workers 8
```

## Upload Telegram

Token chỉ đọc từ environment, không ghi vào index:

```bash
export TELEGRAM_BOT_TOKEN='...'
export TELEGRAM_CHAT_ID='...'

python3 tools/telegram/text_effect_assets.py upload \
  --workers 4 \
  --index tools/telegram/text-effects-telegram-index.json
```

Uploader resume theo `effectId`, retry 429 theo `retry_after`, index cập nhật
atomic sau mỗi batch ngắn.

Index:

```text
tools/telegram/text-effects-telegram-index.json
```

File này bị git-ignore vì là state local.

## App

- Catalog URL:
  `https://raw.githubusercontent.com/votaminh/msc011_file/main/text-effects-preview.json`
- Asset proxy:
  `http://10.0.2.2:8765/api/telegram/text-effect/<effectId>`
- App verify `bytes`, unzip an toàn vào `files/text_effect/<effectId>`.
- Apply qua `TextEffectBridge.apply`.

Runtime verification:

- `verification/text-effects/app-text-effects-catalog-1770.png`
- `verification/text-effects/app-text-effect-applied-art.png`

