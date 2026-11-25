#!/usr/bin/env python3
"""Collect the small Telegram demo set for animations/effects/bubbles."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.request
from pathlib import Path

from telegram.text_animation_assets import api_request, atomic_json, load_json


ROOT = Path(__file__).resolve().parents[1]
PREVIEW_ROOT = Path.home() / "Documents/Android/msc_iaa/011/msc011_file"
TELEGRAM = ROOT / "tools/telegram"
DEMO = ROOT / "demo-upload"
API_ROOT = "https://api.telegram.org"
LIMIT = 10

KINDS = {
    "text-animation": {
        "dir": "text-animations",
        "preview": PREVIEW_ROOT / "text-animation-previews.json",
        "index": TELEGRAM / "text-animations-telegram-index.json",
        "local": ROOT / "asset-vault/text-animations/assets",
    },
    "text-effect": {
        "dir": "text-effects",
        "preview": PREVIEW_ROOT / "text-effects-preview.json",
        "index": TELEGRAM / "text-effects-telegram-index.json",
        "local": ROOT / "asset-vault/text-effects/assets",
    },
    "text-bubble": {
        "dir": "text-bubbles",
        "preview": PREVIEW_ROOT / "text-bubbles-preview.json",
        "index": TELEGRAM / "text-bubbles-telegram-index.json",
        "local": ROOT / "asset-vault/text-bubbles/assets",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def telegram_record(index: dict, effect_id: str) -> dict:
    for item in index.get("items", []):
        if str(item.get("effectId") or "") == effect_id:
            return item
    return {}


def choose_diverse(previews: dict, index: dict, limit: int) -> list[dict]:
    ready = []
    for item in previews.get("items", []):
        effect_id = str(item.get("effectId") or "")
        telegram = telegram_record(index, effect_id)
        if effect_id and telegram.get("file_id"):
            ready.append({
                "preview": item,
                "telegram": telegram,
                "category": (
                    item.get("category")
                    or item.get("categoryName")
                    or "other"
                ),
            })
    buckets: dict[str, list[dict]] = {}
    for entry in ready:
        buckets.setdefault(str(entry["category"]), []).append(entry)
    selected = []
    while len(selected) < limit:
        added = False
        for category in list(buckets):
            bucket = buckets[category]
            if not bucket:
                continue
            selected.append(bucket.pop(0))
            added = True
            if len(selected) >= limit:
                break
        if not added:
            break
    return selected


def download_telegram(token: str, file_id: str, target: Path):
    info = api_request(token, "getFile", {"file_id": file_id})
    file_path = info.get("file_path")
    if not file_path:
        raise RuntimeError("getFile returned no file_path")
    url = f"{API_ROOT}/file/bot{token}/{file_path}"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    with urllib.request.urlopen(url, timeout=60) as response:
        temporary.write_bytes(response.read())
    temporary.replace(target)


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    summary = {}
    for kind, config in KINDS.items():
        previews = load_json(config["preview"], {"items": []})
        index = load_json(config["index"], {"items": []})
        selected = choose_diverse(previews, index, LIMIT)
        destination = DEMO / config["dir"]
        assets = destination / "assets"
        assets.mkdir(parents=True, exist_ok=True)
        manifest_items = []
        for position, entry in enumerate(selected, 1):
            preview = entry["preview"]
            telegram = entry["telegram"]
            effect_id = str(preview["effectId"])
            asset_name = str(telegram.get("asset") or f"{effect_id}.zip")
            target = assets / asset_name
            source = config["local"] / asset_name
            if not target.is_file():
                if source.is_file():
                    shutil.copy2(source, target)
                elif token:
                    download_telegram(token, telegram["file_id"], target)
                else:
                    raise SystemExit(
                        f"Missing local {target}; TELEGRAM_BOT_TOKEN required")
            manifest_items.append({
                "effectId": effect_id,
                "resourceId": str(preview.get("resourceId") or effect_id),
                "name": str(preview.get("name") or effect_id),
                "piloos_name": str(preview.get("piloos_name") or ""),
                "category": str(
                    preview.get("category")
                    or preview.get("categoryName")
                    or ""),
                "asset": asset_name,
                "bytes": target.stat().st_size,
                "sha256": sha256(target),
                "file_id": telegram["file_id"],
                "file_unique_id": telegram.get("file_unique_id") or "",
                "message_id": telegram.get("message_id"),
                "chat_id": str(telegram.get("chat_id") or ""),
            })
            print(
                f"{kind} [{position}/{len(selected)}] "
                f"{preview.get('name')} {target.stat().st_size}B",
                flush=True,
            )
        atomic_json(destination / "manifest.json", {
            "version": 1,
            "kind": kind,
            "rules": {
                "assets": "Telegram",
                "previews": "Git",
                "max": LIMIT,
            },
            "items": manifest_items,
        })
        print(
            f"PASS {kind} items={len(manifest_items)} "
            f"bytes={sum(item['bytes'] for item in manifest_items)}",
            flush=True,
        )
        summary[kind] = {
            "items": len(manifest_items),
            "bytes": sum(item["bytes"] for item in manifest_items),
            "manifest": str(destination / "manifest.json"),
        }
    for manifest_path in sorted(DEMO.glob("*/manifest.json")):
        folder = manifest_path.parent.name
        if folder in ("text-animations", "text-effects", "text-bubbles"):
            continue
        manifest = load_json(manifest_path, {"items": []})
        summary[folder] = {
            "items": len(manifest.get("items", [])),
            "bytes": sum(
                int(item.get("bytes") or 0)
                for item in manifest.get("items", [])
            ),
            "manifest": str(manifest_path),
        }
    for folder_name in ("handwrite", "text-glow"):
        folder = DEMO / folder_name
        files = [
            path for path in folder.glob("*")
            if path.is_file() and not path.name.startswith(".")
        ] if folder.is_dir() else []
        summary[folder_name] = {
            "items": len(files),
            "bytes": sum(path.stat().st_size for path in files),
            "manifest": "",
        }
    atomic_json(DEMO / "manifest.json", {
        "version": 1,
        "rules": {
            "assets": "Telegram",
            "previews": "Git",
            "maxPerKind": LIMIT,
        },
        "kinds": summary,
    })
    print(f"PASS aggregate_manifest={DEMO / 'manifest.json'}", flush=True)


if __name__ == "__main__":
    main()
