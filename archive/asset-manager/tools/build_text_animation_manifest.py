#!/usr/bin/env python3
"""Build the canonical text-animation asset manifest.

The manifest intentionally contains metadata only. Animation ZIPs remain on
disk or Telegram and are referenced by path/file id.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable


REPO = Path(__file__).resolve().parents[1]
ANDROID_ROOT = REPO.parent
PUBLIC_PREVIEW_REPO = Path.home() / "Documents/Android/msc_iaa/011/msc011_file"
CATEGORY_ORDER = {"In": 0, "Out": 1, "Loop": 2}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a deduplicated text-animation metadata manifest."
    )
    parser.add_argument(
        "--assets-index",
        type=Path,
        default=ANDROID_ROOT / "asset-vault/indexes/assets.json",
        help="Asset dashboard canonical assets.json",
    )
    parser.add_argument(
        "--preview-index",
        type=Path,
        default=PUBLIC_PREVIEW_REPO / "text-animation-previews.json",
        help="Public Git text-animation preview index",
    )
    parser.add_argument(
        "--telegram-index",
        type=Path,
        default=REPO / "tools/telegram/text-animations-telegram-index.json",
        help="Telegram file-id index for text animation ZIPs",
    )
    parser.add_argument(
        "--custom-catalog",
        type=Path,
        default=REPO / "app/src/main/assets/text_anim/custom-catalog.json",
        help="Bundled local-only text animation catalog",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO / "asset-manifests/text-animations.json",
    )
    return parser.parse_args()


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def object_items(value: Any, key: str = "items") -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict) and isinstance(value.get(key), list):
        return [item for item in value[key] if isinstance(item, dict)]
    raise ValueError(f"Expected a JSON array or object.{key}[]: {key}")


def text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def integer(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def first_text(*values: Any) -> str:
    for value in values:
        candidate = text(value)
        if candidate:
            return candidate
    return ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def duplicate_groups(
    items: Iterable[dict[str, Any]],
    value_of: Callable[[dict[str, Any]], str],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[str]] = collections.defaultdict(list)
    for item in items:
        value = value_of(item)
        if value:
            grouped[value].append(item["effectId"])
    return [
        {"value": value, "effectIds": sorted(ids), "count": len(ids)}
        for value, ids in sorted(grouped.items())
        if len(ids) > 1
    ]


def write_atomic(target: Path, payload: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=target.name + ".", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_name, target)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def normalize_preview(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not value:
        return None
    return {
        "path": text(value.get("path")),
        "rawUrl": text(value.get("rawUrl")),
        "bytes": integer(value.get("bytes")),
        "sha256": text(value.get("sha256")) or None,
    }


def main() -> int:
    args = parse_args()
    sources = {
        "assetsIndex": args.assets_index.resolve(),
        "previewIndex": args.preview_index.resolve(),
        "telegramIndex": args.telegram_index.resolve(),
    }
    if args.custom_catalog.is_file():
        sources["customCatalog"] = args.custom_catalog.resolve()
    for source in sources.values():
        if not source.is_file():
            raise FileNotFoundError(source)

    asset_items = [
        item
        for item in object_items(read_json(args.assets_index), "assets")
        if text(item.get("kind")) == "text-animation"
    ]
    preview_items = object_items(read_json(args.preview_index))
    telegram_items = object_items(read_json(args.telegram_index))
    custom_items = (
        object_items(read_json(args.custom_catalog))
        if args.custom_catalog.is_file()
        else []
    )

    by_effect: dict[str, dict[str, Any]] = {}
    source_hits: dict[str, set[str]] = collections.defaultdict(set)
    source_rows = (
        ("asset-vault", asset_items),
        ("preview-index", preview_items),
        ("telegram-index", telegram_items),
        ("custom-catalog", custom_items),
    )
    for source_name, rows in source_rows:
        for row in rows:
            effect_id = text(row.get("effectId"))
            if not effect_id:
                continue
            entry = by_effect.setdefault(effect_id, {})
            entry[source_name] = row
            source_hits[effect_id].add(source_name)

    records: list[dict[str, Any]] = []
    for effect_id, merged in by_effect.items():
        custom_local = "custom-catalog" in source_hits[effect_id]
        asset = (
            merged.get("custom-catalog", {})
            if custom_local else merged.get("asset-vault", {})
        )
        preview_item = merged.get("preview-index", {})
        custom_telegram = merged.get("custom-catalog", {}).get("telegram", {})
        telegram = merged.get("telegram-index") or custom_telegram

        preview = normalize_preview(
            asset.get("preview") if custom_local
            else preview_item.get("preview") or asset.get("preview")
        )
        thumb = normalize_preview(
            asset.get("thumb") if custom_local
            else preview_item.get("thumb") or asset.get("thumb")
        )
        asset_telegram = asset.get("telegram")
        if not isinstance(asset_telegram, dict):
            asset_telegram = {}
        preview_telegram = preview_item.get("telegram")
        if not isinstance(preview_telegram, dict):
            preview_telegram = {}

        asset_name = first_text(
            telegram.get("asset"),
            preview_telegram.get("asset"),
            asset_telegram.get("telegramName"),
            f"{effect_id}.zip",
        )
        local_path = text(asset.get("localPath"))
        if not local_path and "custom-catalog" in source_hits[effect_id]:
            local_path = str(ANDROID_ROOT / "text_animations_full" / asset_name)
        local_available = bool(local_path) and Path(local_path).is_file()
        archive_sha = first_text(asset.get("sha256"), telegram.get("sha256"))
        if not archive_sha and local_available:
            archive_sha = sha256_file(Path(local_path))
        archive_bytes = (
            integer(asset.get("bytes"))
            or integer(telegram.get("bytes"))
            or integer(preview_telegram.get("bytes"))
        )
        file_id = first_text(
            telegram.get("file_id"),
            asset_telegram.get("fileId"),
            preview_telegram.get("fileId"),
        )
        file_unique_id = first_text(
            telegram.get("file_unique_id"),
            asset_telegram.get("fileUniqueId"),
            preview_telegram.get("fileUniqueId"),
        )
        category = first_text(
            asset.get("category"),
            telegram.get("category"),
            preview_item.get("category"),
        )
        name = first_text(
            asset.get("name"),
            telegram.get("name"),
            preview_item.get("name"),
        )
        resource_id = first_text(
            asset.get("resourceId"),
            telegram.get("resourceId"),
            preview_item.get("resourceId"),
            effect_id,
        )
        telegram_uploaded = bool(file_id and file_unique_id)
        if local_available and telegram_uploaded:
            status = "local+telegram"
        elif local_available:
            status = "local-only"
        elif telegram_uploaded:
            status = "telegram-only"
        else:
            status = "missing"

        records.append(
            {
                "effectId": effect_id,
                "resourceId": resource_id,
                "name": name,
                "category": category,
                "status": status,
                "sources": sorted(source_hits[effect_id]),
                "archive": {
                    "asset": asset_name,
                    "localPath": local_path or None,
                    "localAvailable": local_available,
                    "bytes": archive_bytes,
                    "sha256": archive_sha or None,
                },
                "telegram": {
                    "uploaded": telegram_uploaded,
                    "fileId": file_id or None,
                    "fileUniqueId": file_unique_id or None,
                    "messageId": integer(
                        telegram.get("message_id")
                        or asset_telegram.get("messageId")
                    ),
                    "asset": asset_name,
                    "bytes": integer(
                        telegram.get("bytes")
                        or asset.get("bytes")
                        or preview_telegram.get("bytes")
                    ),
                    "sha256": first_text(
                        telegram.get("sha256"),
                        archive_sha,
                    )
                    or None,
                },
                "preview": preview,
                "thumb": thumb,
            }
        )

    records.sort(
        key=lambda item: (
            CATEGORY_ORDER.get(item["category"], 99),
            item["name"].casefold(),
            item["effectId"],
        )
    )
    items = {item["effectId"]: item for item in records}

    hard_duplicates = {
        "resourceId": duplicate_groups(records, lambda item: item["resourceId"]),
        "archiveSha256": duplicate_groups(
            records, lambda item: item["archive"]["sha256"] or ""
        ),
        "telegramFileUniqueId": duplicate_groups(
            records, lambda item: item["telegram"]["fileUniqueId"] or ""
        ),
        "localPath": duplicate_groups(
            records, lambda item: item["archive"]["localPath"] or ""
        ),
    }
    blocking_conflicts = {
        key: groups
        for key, groups in hard_duplicates.items()
        if key != "archiveSha256" and groups
    }

    counts = {
        "total": len(records),
        "categories": dict(
            sorted(
                collections.Counter(item["category"] for item in records).items()
            )
        ),
        "localAvailable": sum(
            1 for item in records if item["archive"]["localAvailable"]
        ),
        "telegramAvailable": sum(
            1 for item in records if item["telegram"]["uploaded"]
        ),
        "previewAvailable": sum(
            1 for item in records if item["preview"] is not None
        ),
        "thumbAvailable": sum(1 for item in records if item["thumb"] is not None),
    }
    generated_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    payload = {
        "schemaVersion": 1,
        "kind": "text-animation",
        "generatedAt": generated_at,
        "description": (
            "Canonical inventory of existing CapCut text animations. "
            "Animation ZIPs are stored locally and on Telegram; previews are "
            "stored in the public Git preview repository."
        ),
        "metadataGuide": {
            "effectId": (
                "PRIMARY KEY. Never add another animation with an effectId "
                "already present. This is also the app cache directory and "
                "Telegram proxy key."
            ),
            "resourceId": (
                "Secondary unique key. Keep the original CapCut resourceId; "
                "do not replace it with effectId unless the source really uses "
                "the same value."
            ),
            "name": "Display name from the CapCut animation catalog.",
            "category": "Exactly one of In, Out, or Loop.",
            "archive.asset": "ZIP filename. Use <effectId>.zip.",
            "archive.localPath": (
                "Absolute local ZIP path when the archive is mirrored on disk."
            ),
            "archive.bytes": "Exact ZIP size; the Android asset store verifies it.",
            "archive.sha256": (
                "SHA-256 of the ZIP. A duplicate SHA is a content warning, not "
                "automatically an effectId error."
            ),
            "telegram.fileId": "Bot-API file_id used by the local asset proxy.",
            "telegram.fileUniqueId": (
                "Stable Telegram file identity; must not be reused by another "
                "animation."
            ),
            "preview.rawUrl": (
                "Animated WebP URL served by the public preview repository."
            ),
            "thumb.rawUrl": "Static thumbnail URL served by Git.",
        },
        "duplicatePolicy": {
            "effectId": "block",
            "resourceId": "block",
            "telegram.fileUniqueId": "block",
            "archive.localPath": "block",
            "archive.sha256": (
                "warn: identical bytes may exist under several CapCut effect "
                "IDs; inspect before reusing or deleting"
            ),
        },
        "addAssetChecklist": [
            "Confirm effectId is not present in items.",
            "Confirm resourceId is not present in duplicateGroups.resourceId.",
            "Confirm Telegram fileUniqueId is not already registered.",
            "Confirm local path is not already registered.",
            "Compute ZIP bytes and SHA-256; compare with archiveSha256 warnings.",
            "Use category exactly as In, Out, or Loop.",
            "Add preview and thumb URLs after the Telegram upload succeeds.",
            "Run this generator again and require blockingConflicts to remain empty.",
        ],
        "sources": {key: str(value) for key, value in sources.items()},
        "counts": counts,
        "duplicateGroups": hard_duplicates,
        "blockingConflicts": blocking_conflicts,
        "items": items,
    }
    write_atomic(args.output, payload)

    print(
        f"PASS output={args.output} total={counts['total']} "
        f"local={counts['localAvailable']} "
        f"telegram={counts['telegramAvailable']} "
        f"preview={counts['previewAvailable']} "
        f"blockingConflicts={sum(len(v) for v in blocking_conflicts.values())} "
        f"shaWarnings={len(hard_duplicates['archiveSha256'])}"
    )
    return 2 if blocking_conflicts else 0


if __name__ == "__main__":
    sys.exit(main())
