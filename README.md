# msc011_file

Public preview assets for the CapCut animation catalog. This repository stores
lightweight preview images only; animation ZIP resources are kept on Telegram
and referenced by `file_id` in `text-animation-previews.json`.

## Structure

```text
text-animation-previews.json
previews/
  text-animations/
    animations/
      <effectId>-anim.webp
    thumbs/
      <effectId>-thumb.webp
```

## Index

`text-animation-previews.json` maps each effect to:

- catalog metadata (`name`, `category`, `effectId`, `resourceId`);
- animated preview raw URL and static thumbnail raw URL;
- preview/thumbnail size and SHA-256;
- Telegram ZIP `fileId`, `fileUniqueId` and asset name.

Raw base:

```text
https://raw.githubusercontent.com/votaminh/msc011_file/b7ae5f68a2f1fb94ab8cb998062c0942d5607923
```

Example:

```text
https://raw.githubusercontent.com/votaminh/msc011_file/b7ae5f68a2f1fb94ab8cb998062c0942d5607923/previews/text-animations/animations/7673368613293657360-anim.webp
```
