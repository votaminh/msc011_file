#!/usr/bin/env python3
"""Publish lightweight text-material covers/thumbnails to the public Git repo."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import io
import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image


USER_AGENT = "CapCut-Android/20.0.0"


def load_json(path: Path):
    return json.loads(path.read_text("utf-8"))


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def sniff_extension(payload: bytes, content_type: str, url: str) -> str:
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return ".webp"
    if payload.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if payload.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content_type:
        extension = mimetypes.guess_extension(content_type.split(";", 1)[0])
        if extension:
            return extension
    return Path(urllib.parse.urlparse(url).path).suffix.lower() or ".img"


def download(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = response.read()
        content_type = response.headers.get("Content-Type", "")
    if not payload:
        raise ValueError("empty response")
    if payload[:64].lstrip().lower().startswith((b"<!doctype", b"<html")):
        raise ValueError("received HTML")
    return payload, content_type


def image_thumb(payload: bytes) -> bytes:
    with Image.open(io.BytesIO(payload)) as image:
        image.seek(0)
        rgba = image.convert("RGBA")
        rgba.thumbnail((120, 120), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
        canvas.alpha_composite(
            rgba,
            ((120 - rgba.width) // 2, (120 - rgba.height) // 2),
        )
        output = io.BytesIO()
        canvas.save(output, format="WEBP", quality=82, method=4)
        return output.getvalue()


def categories(runtime: dict) -> list[dict]:
    result = []
    seen = set()
    for category in runtime.get("categories", []):
        category_id = str(category.get("id") or category.get("key") or "")
        if not category_id or category_id in seen:
            continue
        seen.add(category_id)
        result.append({
            "id": category_id,
            "key": category.get("key") or "",
            "name": category.get("name") or category_id,
        })
    return result


def unique_effects(runtime: dict):
    result = {}
    for record in runtime.get("effects", []):
        effect = record.get("effect") or {}
        effect_id = str(effect.get("effectId") or "")
        if not effect_id:
            continue
        current = result.get(effect_id)
        if current is None or (
            not (current.get("effect") or {}).get("staticCoverUrl")
            and effect.get("staticCoverUrl")
        ):
            result[effect_id] = record
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runtime",
        type=Path,
        default=Path(
            "/Users/votaminh99/Documents/Default Project/demo_andorid/"
            "asset-vault/runtime/text-effects-runtime.json"
        ),
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path(
            "/Users/votaminh99/Documents/Android/msc_iaa/011/msc011_file"
        ),
    )
    parser.add_argument(
        "--raw-base",
        default=(
            "https://raw.githubusercontent.com/votaminh/msc011_file/main"
        ),
    )
    parser.add_argument(
        "--kind",
        choices=("text-effects", "text-bubbles"),
        default="text-effects",
    )
    parser.add_argument("--telegram-index", type=Path)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()

    runtime = load_json(args.runtime)
    catalog_categories = categories(runtime)
    unique = unique_effects(runtime)
    telegram_index = {}
    if args.telegram_index and args.telegram_index.is_file():
        telegram_data = load_json(args.telegram_index)
        telegram_index = {
            str(item.get("effectId")): item
            for item in telegram_data.get("items", [])
            if item.get("effectId") and item.get("file_id")
        }
    covers_dir = args.repo / f"previews/{args.kind}/covers"
    thumbs_dir = args.repo / f"previews/{args.kind}/thumbs"
    covers_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    downloaded = {}
    failures = []

    def process(effect_id: str, record: dict):
        effect = record.get("effect") or {}
        source_url = effect.get("staticCoverUrl") or ""
        if not source_url:
            return effect_id, None, "missing staticCoverUrl"
        try:
            payload, content_type = download(source_url)
            extension = sniff_extension(payload, content_type, source_url)
            cover = covers_dir / f"{effect_id}-cover{extension}"
            thumb = thumbs_dir / f"{effect_id}-thumb.webp"
            cover.write_bytes(payload)
            thumb.write_bytes(image_thumb(payload))
            return effect_id, {
                "coverPath": str(cover.relative_to(args.repo)).replace(
                    os.sep, "/"),
                "thumbPath": str(thumb.relative_to(args.repo)).replace(
                    os.sep, "/"),
                "coverBytes": len(payload),
                "coverSha256": hashlib.sha256(payload).hexdigest(),
                "thumbBytes": thumb.stat().st_size,
                "thumbSha256": hashlib.sha256(thumb.read_bytes()).hexdigest(),
                "contentType": content_type,
            }, None
        except Exception as error:
            return effect_id, None, f"{type(error).__name__}: {error}"

    with concurrent.futures.ThreadPoolExecutor(
            max_workers=args.workers) as pool:
        futures = {
            pool.submit(process, effect_id, record): effect_id
            for effect_id, record in unique.items()
        }
        for index, future in enumerate(
                concurrent.futures.as_completed(futures), 1):
            effect_id, result, failure = future.result()
            if result:
                downloaded[effect_id] = result
            if failure:
                failures.append({"effectId": effect_id, "error": failure})
            if index % 50 == 0 or index == len(futures):
                print(
                    f"{index}/{len(futures)} covers={len(downloaded)} "
                    f"failures={len(failures)}",
                    flush=True,
                )

    items = []
    category_names = {item["id"]: item["name"] for item in catalog_categories}
    for record in runtime.get("effects", []):
        effect = record.get("effect") or {}
        effect_id = str(effect.get("effectId") or "")
        preview = downloaded.get(effect_id)
        if not preview:
            continue
        category = record.get("category") or {}
        category_id = str(
            category.get("id") or category.get("key") or "all")
        extra = {}
        try:
            extra = json.loads(effect.get("extra") or "{}")
        except json.JSONDecodeError:
            pass
        telegram = telegram_index.get(effect_id) or {}
        items.append({
            "categoryId": category_id,
            "categoryName": (
                category.get("name")
                or category_names.get(category_id)
                or ("Bubbles" if args.kind == "text-bubbles" else "")
                or category_id
            ),
            "effectId": effect_id,
            "resourceId": effect.get("resourceId") or effect_id,
            "name": effect.get("name") or effect_id,
            "vip": bool(extra.get("is_vip")),
            "business": bool(extra.get("is_business")),
            "preview": {
                "path": preview["coverPath"],
                "rawUrl": (
                    args.raw_base.rstrip("/") + "/" + preview["coverPath"]
                ),
                "bytes": preview["coverBytes"],
                "sha256": preview["coverSha256"],
            },
            "thumb": {
                "path": preview["thumbPath"],
                "rawUrl": (
                    args.raw_base.rstrip("/") + "/" + preview["thumbPath"]
                ),
                "bytes": preview["thumbBytes"],
                "sha256": preview["thumbSha256"],
            },
            "telegram": {
                "fileId": telegram.get("file_id") or "",
                "fileUniqueId": telegram.get("file_unique_id") or "",
                "asset": telegram.get("asset") or "",
                "bytes": telegram.get("bytes") or 0,
            },
        })

    index = {
        "schemaVersion": 1,
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "rawBase": args.raw_base.rstrip("/"),
        "source": str(args.runtime),
        "categories": catalog_categories,
        "count": len(items),
        "uniqueEffects": len(unique),
        "uniquePreviews": len(downloaded),
        "telegramMapped": sum(
            1 for item in items
            if item["telegram"]["fileId"]
        ),
        "items": items,
        "failures": failures,
    }
    destination = args.repo / f"{args.kind}-preview.json"
    atomic_json(destination, index)
    print(
        f"PASS path={destination} categories={len(catalog_categories)} "
        f"items={len(items)} unique={len(downloaded)} failures={len(failures)}"
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
