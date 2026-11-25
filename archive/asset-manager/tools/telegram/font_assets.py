#!/usr/bin/env python3
"""Prepare and upload the ten-font Telegram demo set.

Runtime evidence:
  BaseTextFontPagerViewLifecycle.A0(List<Effect>, boolean)
  smali_classes4/.../BaseTextFontPagerViewLifecycle.smali:449

The full runtime catalog stays in asset-vault. Only the small demo TTF files and
their Telegram file ids are referenced by the app. Preview images remain Git
artifacts.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import struct
import urllib.request
import zipfile
from pathlib import Path

from text_animation_assets import atomic_json, load_json, send_document


USER_AGENT = "CapCut-Android/20.0.0"
ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "asset-vault/runtime/text-fonts-runtime.json"
DEMO = ROOT / "demo-upload/fonts"
ASSETS = DEMO / "assets"
PREVIEWS = DEMO / "previews"
MANIFEST = DEMO / "manifest.json"
INDEX = ROOT / "tools/telegram/fonts-telegram-index.json"

# Stable, non-VIP Trending entries selected from the runtime dump.
FONT_IDS = [
    "7540173324022713616",  # CC-Raven
    "7044868401998598657",  # BANGERS
    "6808050100057674247",  # Italic
    "7697159634477567248",  # SportSans
    "7527979388692892929",  # CC-Seaweed
    "7317175475195875841",  # ZY Resolve
    "7148699606082130433",  # Rubik-Bold
    "6808050433836192264",  # Barlow
    "7512729552410397969",  # CC-Pureline
    "7215802835089232386",  # Arno Pro
]


def first_url(font: dict, kind: str) -> str:
    urls = ((font.get(kind) or {}).get("urls") or [])
    return next((url for url in urls if url.startswith(("http://", "https://"))), "")


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def font_extension(raw: bytes) -> str:
    if raw[:4] == b"\x00\x01\x00\x00":
        return ".ttf"
    if raw[:4] == b"OTTO":
        return ".otf"
    if raw[:4] == b"ttcf":
        return ".ttc"
    if raw[:4] == b"wOFF":
        return ".woff"
    if raw[:4] == b"wOF2":
        return ".woff2"
    raise ValueError(f"unsupported font header {raw[:4]!r}")


def resolve_payload(raw: bytes) -> tuple[str, str, bytes, bytes]:
    """Return format, font entry name, font bytes, and archive bytes."""
    if raw[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = [
                name for name in archive.namelist()
                if not name.startswith("__MACOSX/")
                and name.lower().endswith(
                    (".ttf", ".otf", ".ttc", ".woff", ".woff2"))
            ]
            if not names:
                raise ValueError("font ZIP contains no font file")
            entry = names[0]
            font_bytes = archive.read(entry)
        return (
            font_extension(font_bytes).lstrip("."),
            Path(entry).name,
            font_bytes,
            raw,
        )
    extension = font_extension(raw)
    return extension.lstrip("."), "font" + extension, raw, b""


def table_count(raw: bytes) -> int:
    if raw[:4] in (b"\x00\x01\x00\x00", b"OTTO"):
        return struct.unpack(">H", raw[4:6])[0]
    return 0


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def prepare() -> None:
    runtime = load_json(RUNTIME, None)
    if not isinstance(runtime, dict):
        raise SystemExit(f"Missing runtime catalog: {RUNTIME}")
    rows = {
        str((row.get("font") or {}).get("effectId")): row
        for row in runtime.get("fonts", [])
    }
    missing = [font_id for font_id in FONT_IDS if font_id not in rows]
    if missing:
        raise SystemExit(f"Missing runtime font ids: {missing}")

    ASSETS.mkdir(parents=True, exist_ok=True)
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    previous = load_json(MANIFEST, {"items": []})
    previous_items = {
        str(item.get("effectId")): item
        for item in previous.get("items", [])
        if item.get("effectId")
    }

    items = []
    for position, font_id in enumerate(FONT_IDS, 1):
        row = rows[font_id]
        font = row["font"]
        category = row["category"]
        file_url = first_url(font, "fileUrl")
        preview_url = first_url(font, "iconUrl")
        if not file_url:
            raise SystemExit(f"Font {font_id} has no fileUrl")
        try:
            extra = json.loads(font.get("extra") or "{}")
        except json.JSONDecodeError:
            extra = {}

        raw = fetch(file_url)
        extension, detected_name, font_bytes, original_archive = (
            resolve_payload(raw))
        safe_name = "".join(
            char if char.isalnum() or char in "-_ " else "_"
            for char in (font.get("name") or font_id)
        ).strip() or font_id
        font_name = detected_name or (safe_name + "." + extension)
        archive = ASSETS / f"{font_id}.zip"
        if original_archive:
            archive.write_bytes(original_archive)
        else:
            with zipfile.ZipFile(
                    archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
                output.writestr(font_name, font_bytes)

        preview = PREVIEWS / f"{font_id}.webp"
        if preview_url:
            preview.write_bytes(fetch(preview_url))

        prior = previous_items.get(font_id, {})
        item = {
            "fontId": font_id,
            "effectId": font_id,
            "resourceId": font.get("resourceId") or font_id,
            "name": font.get("name") or font_id,
            "categoryId": category.get("id") or "",
            "categoryName": category.get("name") or "",
            "vip": bool(extra.get("is_vip")),
            "business": bool(extra.get("is_business")),
            "sourcePlatform": int(extra.get("source_platform_ex") or 0),
            "fontMd5": extra.get("font_md5") or "",
            "format": extension,
            "fontFile": font_name,
            "asset": archive.name,
            "path": str(archive),
            "bytes": archive.stat().st_size,
            "sha256": sha256(archive.read_bytes()),
            "fontBytes": len(font_bytes),
            "fontSha256": sha256(font_bytes),
            "tableCount": table_count(font_bytes),
            "preview": str(preview) if preview.is_file() else "",
            "fileUrl": file_url,
            "previewUrl": preview_url,
            "file_id": prior.get("file_id") or "",
            "file_unique_id": prior.get("file_unique_id") or "",
            "message_id": prior.get("message_id"),
            "chat_id": prior.get("chat_id") or "",
            "telegram_file_name": (
                prior.get("telegram_file_name") or archive.name),
        }
        items.append(item)
        print(
            f"[{position}/{len(FONT_IDS)}] {item['name']} "
            f".{extension} {len(font_bytes)}B tables={item['tableCount']} "
            f"zip={item['bytes']}B",
            flush=True,
        )

    manifest = {
        "version": 1,
        "kind": "font-demo",
        "runtime": str(RUNTIME),
        "rules": {
            "assets": "Telegram",
            "previews": "Git",
            "max": 10,
        },
        "items": items,
    }
    atomic_json(MANIFEST, manifest)
    atomic_json(INDEX, {
        "version": 1,
        "items": items,
    })
    print(f"PASS manifest={MANIFEST} items={len(items)}", flush=True)


def upload(chat_id: str | None) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = str(chat_id or os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
    manifest = load_json(MANIFEST, None)
    if not isinstance(manifest, dict):
        raise SystemExit(f"Missing manifest: {MANIFEST}")
    uploaded = 0
    items = manifest.get("items", [])
    for position, item in enumerate(items, 1):
        if item.get("file_id"):
            print(
                f"[{position}/{len(items)}] skip {item['name']} "
                f"{item['file_id']}",
                flush=True,
            )
            continue
        path = Path(item.get("path") or "")
        if not path.is_file():
            raise SystemExit(f"Missing asset: {path}")
        result = send_document(
            token, chat, path, f"{item['name']} | {item['fontId']}")
        document = result.get("document") or {}
        item.update({
            "file_id": document.get("file_id") or "",
            "file_unique_id": document.get("file_unique_id") or "",
            "message_id": result.get("message_id"),
            "chat_id": chat,
            "telegram_file_name": document.get("file_name") or path.name,
        })
        if not item["file_id"]:
            raise SystemExit(f"Telegram returned no file_id for {path.name}")
        atomic_json(MANIFEST, manifest)
        atomic_json(INDEX, {"version": 1, "items": items})
        uploaded += 1
        print(
            f"[{position}/{len(items)}] uploaded {item['name']} "
            f"{item['file_id']}",
            flush=True,
        )
    print(f"PASS uploaded={uploaded} total={len(items)}", flush=True)


def export_app(output: Path) -> None:
    manifest = load_json(MANIFEST, None)
    if not isinstance(manifest, dict):
        raise SystemExit(f"Missing manifest: {MANIFEST}")
    items = []
    for item in manifest.get("items", []):
        if not item.get("file_id"):
            raise SystemExit(f"Font has no Telegram file_id: {item.get('fontId')}")
        items.append({
            key: item.get(key)
            for key in (
                "fontId",
                "effectId",
                "resourceId",
                "name",
                "categoryId",
                "categoryName",
                "vip",
                "business",
                "sourcePlatform",
                "format",
                "fontFile",
                "bytes",
                "sha256",
                "fontSha256",
                "previewUrl",
                "file_id",
            )
        })
    atomic_json(output, {
        "version": 1,
        "kind": "font-demo",
        "rules": {
            "assets": "Telegram",
            "previews": "Git",
            "max": 10,
        },
        "items": items,
    })
    print(f"PASS app_manifest={output} items={len(items)}", flush=True)


def render_previews(repo_root: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    manifest = load_json(MANIFEST, None)
    if not isinstance(manifest, dict):
        raise SystemExit(f"Missing manifest: {MANIFEST}")
    preview_dir = repo_root / "previews/fonts"
    thumb_dir = preview_dir / "thumbs"
    preview_dir.mkdir(parents=True, exist_ok=True)
    thumb_dir.mkdir(parents=True, exist_ok=True)
    label_font = ImageFont.truetype(
        "/System/Library/Fonts/Supplemental/Arial.ttf", 28)
    small_font = ImageFont.truetype(
        "/System/Library/Fonts/Supplemental/Arial.ttf", 22)
    items = []
    for position, item in enumerate(manifest.get("items", []), 1):
        archive_path = Path(item["path"])
        with zipfile.ZipFile(archive_path) as archive:
            font_names = [
                name for name in archive.namelist()
                if name.lower().endswith(
                    (".ttf", ".otf", ".ttc", ".woff", ".woff2"))
            ]
            if not font_names:
                raise SystemExit(f"No font in {archive_path}")
            font_bytes = archive.read(font_names[0])

        image = Image.new("RGB", (720, 360), "#0E0F14")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (24, 24, 696, 336), radius=28, fill="#14151C",
            outline="#23252F", width=2)
        draw.text(
            (52, 44),
            f"CAPCUT 20  ·  {(item.get('categoryName') or '').upper()}",
            font=small_font, fill="#6EE7B7")
        sample = "Aa Bb 0123"
        selected = None
        for size in range(104, 51, -4):
            try:
                candidate = ImageFont.truetype(
                    io.BytesIO(font_bytes), size)
            except Exception:
                candidate = ImageFont.truetype(
                    io.BytesIO(font_bytes), size, index=0)
            box = draw.textbbox((0, 0), sample, font=candidate)
            if box[2] - box[0] <= 620:
                selected = candidate
                break
        if selected is None:
            selected = ImageFont.truetype(io.BytesIO(font_bytes), 52)
        box = draw.textbbox((0, 0), sample, font=selected)
        width = box[2] - box[0]
        height = box[3] - box[1]
        draw.text(
            ((720 - width) / 2 - box[0], 166 - height / 2 - box[1]),
            sample, font=selected, fill="#F2F3F7")
        draw.text(
            (52, 292), item.get("name") or item["fontId"],
            font=label_font, fill="#F2F3F7")
        draw.text(
            (668, 298), item.get("format", "").upper(),
            font=small_font, fill="#9BA1B0", anchor="ra")

        preview = preview_dir / f"{item['fontId']}.webp"
        thumb = thumb_dir / f"{item['fontId']}.webp"
        image.save(preview, "WEBP", quality=90, method=6)
        image.resize((240, 120), Image.Resampling.LANCZOS).save(
            thumb, "WEBP", quality=82, method=6)
        items.append({
            "effectId": item["fontId"],
            "resourceId": item["resourceId"],
            "name": item["name"],
            "categoryId": item["categoryId"],
            "categoryName": item["categoryName"],
            "vip": item["vip"],
            "format": item["format"],
            "preview": {
                "path": f"previews/fonts/{preview.name}",
                "bytes": preview.stat().st_size,
                "sha256": sha256(preview.read_bytes()),
            },
            "thumb": {
                "path": f"previews/fonts/thumbs/{thumb.name}",
                "bytes": thumb.stat().st_size,
                "sha256": sha256(thumb.read_bytes()),
            },
            "telegram": {
                "file_id": item.get("file_id") or "",
                "bytes": item.get("bytes"),
                "sha256": item.get("sha256"),
            },
        })
        print(
            f"[{position}/{len(manifest.get('items', []))}] preview "
            f"{item['name']} {preview.stat().st_size}B",
            flush=True,
        )
    preview_index = repo_root / "font-previews.json"
    atomic_json(preview_index, {
        "schemaVersion": 1,
        "source": "CapCut 20.0.0 runtime text-font catalog",
        "count": len(items),
        "items": items,
    })
    print(f"PASS preview_index={preview_index} items={len(items)}")


def main() -> None:
    if not RUNTIME.is_file():
        raise SystemExit(f"Missing runtime catalog: {RUNTIME}")
    import argparse
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.set_defaults(func=lambda _args: prepare())
    upload_parser = subparsers.add_parser("upload")
    upload_parser.add_argument("--chat-id")
    upload_parser.set_defaults(func=lambda args: upload(args.chat_id))
    export_parser = subparsers.add_parser("export-app")
    export_parser.add_argument("--output", type=Path, required=True)
    export_parser.set_defaults(func=lambda args: export_app(args.output))
    preview_parser = subparsers.add_parser("previews")
    preview_parser.add_argument(
        "--repo-root", type=Path,
        default=Path("/Users/votaminh99/Documents/Android/msc_iaa/011/msc011_file"))
    preview_parser.set_defaults(
        func=lambda args: render_previews(args.repo_root))
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
