#!/usr/bin/env python3
"""Local-only asset vault dashboard.

Run:
  python3 tools/asset_dashboard/server.py \
    --vault "/Users/votaminh99/Documents/Default Project/demo_andorid/asset-vault"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import Counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
PARENT = REPO.parent
DEFAULT_VAULT = PARENT / "asset-vault"
APP_ASSETS = REPO / "app/src/main/assets"
FULL_ANIMATIONS = PARENT / "text_animations_full"
REPO_TELEGRAM_INDEX = REPO / "tools/telegram/text-animations-telegram-index.json"
DEFAULT_PREVIEW_INDEX = (
    Path.home() / "Documents/Android/msc_iaa/011/msc011_file/"
    "text-animation-previews.json"
)
DEFAULT_TEXT_EFFECT_PREVIEW_INDEX = (
    Path.home() / "Documents/Android/msc_iaa/011/msc011_file/"
    "text-effects-preview.json"
)
DEFAULT_TEXT_BUBBLE_PREVIEW_INDEX = (
    Path.home() / "Documents/Android/msc_iaa/011/msc011_file/"
    "text-bubbles-preview.json"
)
DEFAULT_TEXT_TEMPLATE_PREVIEW_INDEX = (
    Path.home() / "Documents/Android/msc_iaa/011/msc011_file/"
    "text-templates-preview.json"
)
DEFAULT_FONT_PREVIEW_INDEX = (
    Path.home() / "Documents/Android/msc_iaa/011/msc011_file/"
    "font-previews.json"
)
PREVIEW_REPO_ROOT = (
    Path.home() / "Documents/Android/msc_iaa/011/msc011_file"
)
PUBLIC_PREVIEW_BASE = (
    "https://raw.githubusercontent.com/votaminh/msc011_file/main/"
)
TEXT_EFFECT_TELEGRAM_INDEX = (
    REPO / "tools/telegram/text-effects-telegram-index.json"
)
TEXT_BUBBLE_TELEGRAM_INDEX = (
    REPO / "tools/telegram/text-bubbles-telegram-index.json"
)
TEXT_TEMPLATE_TELEGRAM_INDEX = (
    REPO / "tools/telegram/text-templates-telegram-index.json"
)
FONT_TELEGRAM_INDEX = REPO / "tools/telegram/fonts-telegram-index.json"
EFFECT_MODEL_ROOT = REPO / "asset-vault/models/effectmodel/files"
STATIC_ROOT = Path(__file__).with_name("static")
TELEGRAM_API = "https://api.telegram.org"
MAX_ASSET_BYTES = 64 * 1024 * 1024

SCHEMA_VERSION = 1
INDEX_LOCK = threading.RLock()


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def load_json(path: Path, default):
    if not path.is_file():
        return default
    return json.loads(path.read_text("utf-8"))


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def vault_paths(vault: Path):
    return {
        "root": vault,
        "objects": vault / "objects",
        "indexes": vault / "indexes",
        "generated": vault / "generated",
        "staging": vault / "staging",
        "quarantine": vault / "quarantine",
        "cache": vault / "cache",
        "assets": vault / "indexes/assets.json",
        "telegram": vault / "indexes/telegram-file-ids.json",
    }


def initialize_vault(vault: Path):
    paths = vault_paths(vault)
    for key in ("objects", "indexes", "generated", "staging", "quarantine", "cache"):
        paths[key].mkdir(parents=True, exist_ok=True)
    (paths["objects"] / "text-animation").mkdir(exist_ok=True)
    (paths["objects"] / "video-effect").mkdir(exist_ok=True)
    (paths["objects"] / "text-effect").mkdir(exist_ok=True)
    (paths["objects"] / "script-runtime").mkdir(exist_ok=True)
    (paths["objects"] / "font").mkdir(exist_ok=True)
    (paths["objects"] / "media").mkdir(exist_ok=True)
    (paths["cache"] / "extracted").mkdir(exist_ok=True)
    if not paths["assets"].is_file():
        atomic_json(paths["assets"], {
            "schemaVersion": SCHEMA_VERSION,
            "updatedAt": now_iso(),
            "assets": [],
        })
    if not paths["telegram"].is_file() and REPO_TELEGRAM_INDEX.is_file():
        shutil.copy2(REPO_TELEGRAM_INDEX, paths["telegram"])
    return paths


def asset_record(
    *,
    asset_id: str,
    kind: str,
    name: str,
    category: str = "",
    effect_id: str = "",
    resource_id: str = "",
    path: Path | None = None,
    source: str = "",
    status: str = "available",
    available: bool = True,
    extra: dict | None = None,
):
    result = {
        "assetId": asset_id,
        "kind": kind,
        "name": name,
        "category": category,
        "effectId": effect_id,
        "resourceId": resource_id or effect_id,
        "status": status,
        "available": available,
        "sourceMode": "external",
        "source": source,
        "localPath": str(path) if path else "",
        "bytes": path.stat().st_size if path and path.is_file() else 0,
        "updatedAt": now_iso(),
    }
    if path and path.is_file():
        result["sha256"] = sha256_file(path)
    if extra:
        result.update(extra)
    return result


def read_telegram(vault: Path) -> dict[str, dict]:
    paths = vault_paths(vault)
    source = paths["telegram"]
    if not source.is_file():
        source = REPO_TELEGRAM_INDEX
    index = load_json(source, {"items": []})
    result = {}
    for item in index.get("items", []):
        effect_id = str(item.get("effectId") or "").strip()
        if effect_id and item.get("file_id"):
            result[effect_id] = {
                "ready": True,
                "fileId": item.get("file_id"),
                "fileUniqueId": item.get("file_unique_id"),
                "messageId": item.get("message_id"),
                "chatId": index.get("chat_id"),
                "telegramName": item.get("telegram_file_name"),
            }
    return result


def read_previews(path: Path | None) -> dict[str, dict]:
    if path is None or not path.is_file():
        return {}
    index = load_json(path, {"items": []})
    previews = {}
    for item in index.get("items", []):
        effect_id = str(item.get("effectId") or "")
        if not effect_id:
            continue
        telegram = normalize_telegram(item.get("telegram") or item)
        if telegram.get("ready"):
            item["telegram"] = telegram
        preview = item.get("preview")
        thumb = item.get("thumb")
        if isinstance(preview, dict):
            item["previewUrl"] = preview.get("rawUrl") or ""
            item["previewPath"] = preview.get("path") or ""
            if not item["previewUrl"] and item["previewPath"]:
                item["previewUrl"] = PUBLIC_PREVIEW_BASE + item["previewPath"]
        elif isinstance(preview, str):
            item["previewUrl"] = preview
        if isinstance(thumb, dict):
            item["thumbUrl"] = thumb.get("rawUrl") or ""
            item["thumbPath"] = thumb.get("path") or ""
            if not item["thumbUrl"] and item["thumbPath"]:
                item["thumbUrl"] = PUBLIC_PREVIEW_BASE + item["thumbPath"]
        elif isinstance(thumb, str):
            item["thumbUrl"] = thumb
        previews[effect_id] = item
    return previews


def normalize_telegram(source: dict | None, chat_id="") -> dict:
    source = source or {}
    nested = source.get("telegram") if isinstance(
        source.get("telegram"), dict) else {}
    file_id = (
        nested.get("fileId")
        or nested.get("file_id")
        or source.get("fileId")
        or source.get("file_id")
    )
    if not file_id:
        return {"ready": False}
    return {
        "ready": True,
        "fileId": file_id,
        "fileUniqueId": (
            nested.get("fileUniqueId")
            or nested.get("file_unique_id")
            or source.get("fileUniqueId")
            or source.get("file_unique_id")
        ),
        "messageId": nested.get("messageId") or source.get("message_id"),
        "chatId": chat_id or source.get("chat_id"),
        "asset": (
            nested.get("asset")
            or source.get("asset")
            or source.get("telegram_file_name")
        ),
        "bytes": nested.get("bytes") or source.get("bytes"),
        "sha256": nested.get("sha256") or source.get("sha256"),
        "localPath": source.get("path") or "",
    }


def read_telegram_catalog(path: Path) -> dict[str, dict]:
    index = load_json(path, {"items": []})
    chat_id = index.get("chat_id") or ""
    records = {}
    for item in index.get("items", []):
        effect_id = str(item.get("effectId") or item.get("fontId") or "")
        record = normalize_telegram(item, chat_id)
        if effect_id and record.get("ready"):
            records[effect_id] = record
    return records


def resolve_indexed_asset(kind: str, item: dict) -> Path | None:
    asset = Path(str(item.get("asset") or "")).name
    raw = Path(str(item.get("path") or ""))
    roots = {
        "text-effect": REPO / "asset-vault/text-effects/assets",
        "text-bubble": REPO / "asset-vault/text-bubbles/assets",
        "text-template": REPO / "demo-upload/text-templates/assets",
        "font": REPO / "demo-upload/fonts/assets",
    }
    candidates = [raw]
    if asset and kind in roots:
        candidates.append(roots[kind] / asset)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def telegram_asset_bytes(effect_id: str, preview_index: Path | None):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    item = read_previews(preview_index).get(effect_id)
    telegram = (item or {}).get("telegram") or {}
    file_id = telegram.get("fileId")
    if not file_id:
        raise LookupError("No Telegram fileId for effect " + effect_id)

    query = urllib.parse.urlencode({"file_id": file_id})
    request = urllib.request.Request(
        f"{TELEGRAM_API}/bot{token}/getFile?{query}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError) as error:
        raise RuntimeError("Telegram getFile failed") from error
    if not result.get("ok"):
        raise RuntimeError("Telegram getFile returned an error")
    file_path = result["result"].get("file_path")
    if not file_path:
        raise RuntimeError("Telegram response has no file_path")

    file_url = f"{TELEGRAM_API}/file/bot{token}/{file_path}"
    try:
        with urllib.request.urlopen(file_url, timeout=45) as response:
            content_length = int(response.headers.get("Content-Length") or 0)
            if content_length > MAX_ASSET_BYTES:
                raise ValueError("Telegram asset is too large")
            body = response.read(MAX_ASSET_BYTES + 1)
    except (urllib.error.HTTPError, urllib.error.URLError) as error:
        raise RuntimeError("Telegram file download failed") from error
    if len(body) > MAX_ASSET_BYTES:
        raise ValueError("Telegram asset is too large")
    return body, telegram.get("asset") or f"{effect_id}.zip"


def attach_telegram(
    asset: dict,
    telegram: dict[str, dict],
    preview_telegram: dict | None = None,
):
    effect_id = str(asset.get("effectId") or "")
    asset["telegram"] = (
        telegram.get(effect_id)
        or (preview_telegram if preview_telegram and preview_telegram.get("ready") else None)
        or {"ready": False}
    )
    return asset


def collect_text_animations(
    telegram: dict[str, dict],
    previews: dict[str, dict],
) -> list[dict]:
    catalog_path = FULL_ANIMATIONS / "catalog.full.json"
    if not catalog_path.is_file():
        return []
    catalog = load_json(catalog_path, {"items": []})
    full_dir = FULL_ANIMATIONS
    app_anim_dir = APP_ASSETS / "text_animations"
    records = []
    for item in catalog.get("items", []):
        effect_id = str(item.get("effectId") or "").strip()
        file_name = Path(str(item.get("asset") or "")).name
        if not effect_id or not file_name:
            continue
        path = full_dir / file_name
        if not path.is_file():
            path = app_anim_dir / file_name
        if not path.is_file():
            record = asset_record(
                asset_id=f"text-animation:{effect_id}",
                kind="text-animation",
                name=str(item.get("name") or effect_id),
                category=str(item.get("category") or ""),
                effect_id=effect_id,
                resource_id=str(item.get("resourceId") or effect_id),
                available=False,
                status="missing",
                source="catalog.full.json",
            )
        else:
            record = asset_record(
                asset_id=f"text-animation:{effect_id}",
                kind="text-animation",
                name=str(item.get("name") or effect_id),
                category=str(item.get("category") or ""),
                effect_id=effect_id,
                resource_id=str(item.get("resourceId") or effect_id),
                path=path,
                source=str(path.parent),
            )
        preview = previews.get(effect_id)
        if preview:
            record["preview"] = preview.get("preview")
            record["thumb"] = preview.get("thumb")
            record["previewUrl"] = (preview.get("preview") or {}).get("rawUrl")
            record["thumbUrl"] = (preview.get("thumb") or {}).get("rawUrl")
        records.append(attach_telegram(
            record,
            telegram,
            (preview or {}).get("telegram"),
        ))
    return records


def collect_video_effects() -> list[dict]:
    catalog_path = APP_ASSETS / "capcut_video_effects/catalog.json"
    if not catalog_path.is_file():
        return []
    catalog = load_json(catalog_path, {"effects": []})
    records = []
    seen = set()
    for row in catalog.get("effects", []):
        effect = row.get("effect") or {}
        category = row.get("category") or {}
        effect_id = str(effect.get("effectId") or "").strip()
        if not effect_id or effect_id in seen:
            continue
        seen.add(effect_id)
        cover = str(effect.get("coverAsset") or "")
        cover_path = APP_ASSETS / cover if cover else None
        available = bool(cover_path and cover_path.is_file())
        record = asset_record(
            asset_id=f"video-effect:{effect_id}",
            kind="video-effect",
            name=str(effect.get("name") or effect_id),
            category=str(category.get("name") or ""),
            effect_id=effect_id,
            resource_id=str(effect.get("resourceId") or effect_id),
            path=cover_path if available else None,
            source=str(catalog_path),
            status="metadata" if not available else "preview-only",
            available=available,
            extra={
                "catalogId": str(effect.get("id") or ""),
                "legacyEffectId": str(effect.get("legacyEffectId") or ""),
                "coverAsset": cover,
            },
        )
        records.append(record)
    return records


def collect_known_files() -> list[dict]:
    known = [
        (
            "script-runtime",
            "SegmentJS",
            APP_ASSETS / "model/SegmentJS/SegmentJS.zip",
            "runtime",
        ),
        (
            "text-effect",
            "Text Warp (curve_text)",
            APP_ASSETS / "curve_text_new.zip",
            "text-effect",
        ),
        (
            "text-animation",
            "Appear",
            APP_ASSETS / "epilogue_anim.zip",
            "builtin",
        ),
        (
            "style-catalog",
            "CapCut Text Styles v2",
            APP_ASSETS / "capcut_text/textStyle_v2.txt",
            "catalog",
        ),
        ("media", "Green timer 10s", APP_ASSETS / "sample_video_green_timer.mp4", "sample"),
        ("media", "Sample video", APP_ASSETS / "sample_video.mp4", "sample"),
        ("media", "Sample audio", APP_ASSETS / "sample_audio.m4a", "sample"),
        ("media", "Sample image", APP_ASSETS / "sample_image.png", "sample"),
    ]
    records = []
    for kind, name, path, category in known:
        if not path.is_file():
            continue
        digest = sha256_file(path)
        records.append(asset_record(
            asset_id=f"{kind}:{digest[:20]}",
            kind=kind,
            name=name,
            category=category,
            path=path,
            source="app/src/main/assets",
        ))
    for pack in APP_ASSETS.glob("capcut_video_effects/*"):
        if not pack.is_dir() or pack.name == "covers":
            continue
        size = sum(item.stat().st_size for item in pack.rglob("*") if item.is_file())
        records.append({
            "assetId": f"video-effect-pack:{pack.name}",
            "kind": "video-effect-pack",
            "name": pack.name,
            "category": "local-pack",
            "effectId": "",
            "resourceId": "",
            "status": "directory",
            "available": True,
            "sourceMode": "external",
            "source": "app/src/main/assets/capcut_video_effects",
            "localPath": str(pack),
            "bytes": size,
            "updatedAt": now_iso(),
            "telegram": {"ready": False},
        })
    return records


def collect_effect_models() -> list[dict]:
    if not EFFECT_MODEL_ROOT.is_dir():
        return []
    records = []
    for path in EFFECT_MODEL_ROOT.rglob("*"):
        if not path.is_file() or path.name == ".DS_Store":
            continue
        relative = path.relative_to(EFFECT_MODEL_ROOT).as_posix()
        records.append(asset_record(
            asset_id=f"effect-model:{relative}",
            kind="effect-model",
            name=path.name,
            category=path.parent.name,
            path=path,
            source="CapCut runtime effectmodel cache",
        ))
    return records


def collect_preview_assets(
    kind: str,
    preview_path: Path,
    telegram_path: Path,
) -> list[dict]:
    previews = read_previews(preview_path)
    telegram = read_telegram_catalog(telegram_path)
    records = []
    for effect_id, item in previews.items():
        telegram_record = (
            telegram.get(effect_id)
            or normalize_telegram(item.get("telegram") or item)
        )
        indexed = telegram.get(effect_id) or {}
        local_path = resolve_indexed_asset(kind, indexed or item)
        record = asset_record(
            asset_id=f"{kind}:{effect_id}",
            kind=kind,
            name=str(item.get("name") or effect_id),
            category=str(
                item.get("categoryName")
                or item.get("category")
                or ""
            ),
            effect_id=effect_id,
            resource_id=str(item.get("resourceId") or effect_id),
            path=local_path,
            source=str(preview_path),
            status="ready" if local_path else "missing",
            available=bool(local_path),
            extra={
                "previewUrl": item.get("previewUrl") or "",
                "thumbUrl": item.get("thumbUrl") or "",
                "previewPath": item.get("previewPath") or "",
                "thumbPath": item.get("thumbPath") or "",
                "vip": bool(item.get("vip")),
                "business": bool(item.get("business")),
                "format": item.get("format") or "",
                "telegram": telegram_record,
            },
        )
        if not record.get("bytes") and telegram_record.get("bytes"):
            record["bytes"] = telegram_record["bytes"]
        if not record.get("sha256") and telegram_record.get("sha256"):
            record["sha256"] = telegram_record["sha256"]
        records.append(record)
    return records


def scan_vault(
    vault: Path,
    preview_index: Path | None = None,
    text_effect_preview_index: Path | None = None,
    text_bubble_preview_index: Path | None = None,
    text_template_preview_index: Path | None = None,
    font_preview_index: Path | None = None,
):
    with INDEX_LOCK:
        paths = initialize_vault(vault)
        telegram = read_telegram(vault)
        previews = read_previews(preview_index)
        text_effect_preview_index = (
            text_effect_preview_index or DEFAULT_TEXT_EFFECT_PREVIEW_INDEX
        )
        text_bubble_preview_index = (
            text_bubble_preview_index or DEFAULT_TEXT_BUBBLE_PREVIEW_INDEX
        )
        text_template_preview_index = (
            text_template_preview_index or DEFAULT_TEXT_TEMPLATE_PREVIEW_INDEX
        )
        font_preview_index = font_preview_index or DEFAULT_FONT_PREVIEW_INDEX
        scanned_items = (
            collect_text_animations(telegram, previews)
            + collect_preview_assets(
                "text-animation",
                preview_index or DEFAULT_PREVIEW_INDEX,
                REPO_TELEGRAM_INDEX,
            )
            + collect_video_effects()
            + collect_known_files()
            + collect_effect_models()
            + collect_preview_assets(
                "text-effect",
                text_effect_preview_index,
                TEXT_EFFECT_TELEGRAM_INDEX,
            )
            + collect_preview_assets(
                "text-bubble",
                text_bubble_preview_index,
                TEXT_BUBBLE_TELEGRAM_INDEX,
            )
            + collect_preview_assets(
                "text-template",
                text_template_preview_index,
                TEXT_TEMPLATE_TELEGRAM_INDEX,
            )
            + collect_preview_assets(
                "font",
                font_preview_index,
                FONT_TELEGRAM_INDEX,
            )
        )
        scanned_by_id = {
            item["assetId"]: item
            for item in scanned_items
        }
        scanned = list(scanned_by_id.values())
        scanned_ids = {item["assetId"] for item in scanned}
        previous = load_json(paths["assets"], {"assets": []})
        retained = [
            item for item in previous.get("assets", [])
            if item.get("assetId") not in scanned_ids
        ]
        all_assets = sorted(
            {
                item["assetId"]: item
                for item in retained + scanned
            }.values(),
            key=lambda item: (
                str(item.get("kind") or ""),
                str(item.get("category") or ""),
                str(item.get("name") or "").lower(),
            ),
        )
        index = {
            "schemaVersion": SCHEMA_VERSION,
            "updatedAt": now_iso(),
            "vault": str(vault),
            "sources": {
                "fullTextAnimations": str(FULL_ANIMATIONS),
                "appAssets": str(APP_ASSETS),
                "telegramIndex": str(paths["telegram"]),
                "previewIndex": str(preview_index) if preview_index else "",
                "textEffectPreviewIndex": str(text_effect_preview_index),
                "textBubblePreviewIndex": str(text_bubble_preview_index),
                "textTemplatePreviewIndex": str(text_template_preview_index),
                "fontPreviewIndex": str(font_preview_index),
            },
            "assets": all_assets,
        }
        atomic_json(paths["assets"], index)
        return state_for(vault)


def summary_for(assets: list[dict]) -> dict:
    kinds = Counter(str(item.get("kind") or "unknown") for item in assets)
    categories = Counter(
        str(item.get("category") or "none") for item in assets
        if item.get("kind") == "text-animation"
    )
    return {
        "total": len(assets),
        "available": sum(1 for item in assets if item.get("available")),
        "missing": sum(1 for item in assets if item.get("status") == "missing"),
        "telegramReady": sum(
            1 for item in assets if (item.get("telegram") or {}).get("ready")
        ),
        "totalBytes": sum(int(item.get("bytes") or 0) for item in assets),
        "kinds": dict(sorted(kinds.items())),
        "textAnimationCategories": dict(sorted(categories.items())),
    }


def state_for(vault: Path) -> dict:
    paths = initialize_vault(vault)
    index = load_json(paths["assets"], {
        "schemaVersion": SCHEMA_VERSION,
        "assets": [],
    })
    if not index.get("assets"):
        return scan_vault(vault)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "vault": str(vault),
        "updatedAt": index.get("updatedAt"),
        "sources": index.get("sources", {}),
        "summary": summary_for(index.get("assets", [])),
        "assets": index.get("assets", []),
    }


def add_asset(vault: Path, payload: dict):
    source = Path(str(payload.get("path") or "")).expanduser()
    if not source.is_absolute():
        raise ValueError("Asset path must be absolute")
    if not source.exists() or not source.is_file():
        raise ValueError(f"Asset file not found: {source}")
    kind = str(payload.get("kind") or "other").strip()
    effect_id = str(payload.get("effectId") or "").strip()
    name = str(payload.get("name") or source.stem).strip()
    category = str(payload.get("category") or "").strip()
    digest = sha256_file(source)
    asset_id = (
        f"{kind}:{effect_id}" if effect_id else f"{kind}:{digest[:20]}"
    )
    paths = initialize_vault(vault)
    target = source
    source_mode = "external"
    if payload.get("copy"):
        object_dir = paths["objects"] / kind / (
            effect_id or digest[:20]
        )
        object_dir.mkdir(parents=True, exist_ok=True)
        target = object_dir / source.name
        if not target.exists():
            shutil.copy2(source, target)
        source_mode = "managed"
    record = asset_record(
        asset_id=asset_id,
        kind=kind,
        name=name,
        category=category,
        effect_id=effect_id,
        path=target,
        source=str(source),
    )
    record["sourceMode"] = source_mode
    record["sha256"] = digest
    record["telegram"] = {"ready": False}
    with INDEX_LOCK:
        index = load_json(paths["assets"], {"schemaVersion": SCHEMA_VERSION, "assets": []})
        assets = [
            item for item in index.get("assets", [])
            if item.get("assetId") != asset_id
        ]
        assets.append(record)
        index["assets"] = sorted(
            assets,
            key=lambda item: (
                str(item.get("kind") or ""),
                str(item.get("category") or ""),
                str(item.get("name") or "").lower(),
            ),
        )
        index["updatedAt"] = now_iso()
        index["vault"] = str(vault)
        atomic_json(paths["assets"], index)
    return state_for(vault)


def patch_asset(vault: Path, asset_id: str, payload: dict):
    paths = initialize_vault(vault)
    with INDEX_LOCK:
        index = load_json(paths["assets"], {"assets": []})
        found = False
        for item in index.get("assets", []):
            if item.get("assetId") != asset_id:
                continue
            found = True
            for key in ("name", "category", "status"):
                if key in payload:
                    item[key] = str(payload[key])
            if isinstance(payload.get("tags"), list):
                item["tags"] = [str(value) for value in payload["tags"]]
            item["updatedAt"] = now_iso()
        if not found:
            raise KeyError(asset_id)
        index["updatedAt"] = now_iso()
        atomic_json(paths["assets"], index)
    return state_for(vault)


class DashboardHandler(BaseHTTPRequestHandler):
    vault = DEFAULT_VAULT
    preview_index: Path | None = None
    text_effect_preview_index: Path | None = None
    text_bubble_preview_index: Path | None = None
    text_template_preview_index: Path | None = None
    font_preview_index: Path | None = None

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} {fmt % args}")

    def send_json(self, value, status=HTTPStatus.OK):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status, message):
        self.send_json({"ok": False, "error": message}, status)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > 4 * 1024 * 1024:
            raise ValueError("Request body too large")
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8") or "{}")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/state":
            self.send_json({"ok": True, "state": state_for(self.vault)})
            return
        if parsed.path == "/api/health":
            self.send_json({"ok": True, "vault": str(self.vault)})
            return
        asset_prefix = "/api/telegram/text-animation/"
        if parsed.path.startswith(asset_prefix):
            effect_id = urllib.parse.unquote(parsed.path[len(asset_prefix):])
            if not effect_id:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "Missing effectId")
                return
            try:
                body, filename = telegram_asset_bytes(
                    effect_id, self.preview_index)
            except LookupError as error:
                self.send_error_json(HTTPStatus.NOT_FOUND, str(error))
                return
            except Exception as error:
                self.send_error_json(HTTPStatus.BAD_GATEWAY, str(error))
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(body)))
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{filename}"',
            )
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        text_effect_prefix = "/api/telegram/text-effect/"
        if parsed.path.startswith(text_effect_prefix):
            effect_id = urllib.parse.unquote(
                parsed.path[len(text_effect_prefix):])
            if not effect_id:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "Missing effectId")
                return
            try:
                body, filename = telegram_asset_bytes(
                    effect_id, self.text_effect_preview_index)
            except LookupError as error:
                self.send_error_json(HTTPStatus.NOT_FOUND, str(error))
                return
            except Exception as error:
                self.send_error_json(HTTPStatus.BAD_GATEWAY, str(error))
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(body)))
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{filename}"',
            )
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        text_bubble_prefix = "/api/telegram/text-bubble/"
        if parsed.path.startswith(text_bubble_prefix):
            effect_id = urllib.parse.unquote(
                parsed.path[len(text_bubble_prefix):])
            if not effect_id:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "Missing effectId")
                return
            try:
                body, filename = telegram_asset_bytes(
                    effect_id, self.text_bubble_preview_index)
            except LookupError as error:
                self.send_error_json(HTTPStatus.NOT_FOUND, str(error))
                return
            except Exception as error:
                self.send_error_json(HTTPStatus.BAD_GATEWAY, str(error))
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(body)))
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{filename}"',
            )
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        text_template_prefix = "/api/telegram/text-template/"
        if parsed.path.startswith(text_template_prefix):
            effect_id = urllib.parse.unquote(
                parsed.path[len(text_template_prefix):])
            if not effect_id:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "Missing effectId")
                return
            try:
                body, filename = telegram_asset_bytes(
                    effect_id, TEXT_TEMPLATE_TELEGRAM_INDEX)
            except LookupError as error:
                self.send_error_json(HTTPStatus.NOT_FOUND, str(error))
                return
            except Exception as error:
                self.send_error_json(HTTPStatus.BAD_GATEWAY, str(error))
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(body)))
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{filename}"',
            )
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        font_prefix = "/api/telegram/font/"
        if parsed.path.startswith(font_prefix):
            effect_id = urllib.parse.unquote(
                parsed.path[len(font_prefix):])
            if not effect_id:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "Missing effectId")
                return
            try:
                body, filename = telegram_asset_bytes(
                    effect_id, FONT_TELEGRAM_INDEX)
            except LookupError as error:
                self.send_error_json(HTTPStatus.NOT_FOUND, str(error))
                return
            except Exception as error:
                self.send_error_json(HTTPStatus.BAD_GATEWAY, str(error))
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(body)))
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{filename}"',
            )
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        self.serve_static(parsed.path)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/scan":
                self.send_json({
                    "ok": True,
                    "state": scan_vault(
                        self.vault,
                        self.preview_index,
                        self.text_effect_preview_index,
                        self.text_bubble_preview_index,
                        self.text_template_preview_index,
                        self.font_preview_index,
                    ),
                })
                return
            if parsed.path == "/api/asset":
                payload = self.read_json_body()
                self.send_json({"ok": True, "state": add_asset(self.vault, payload)})
                return
            if parsed.path == "/api/telegram/reload":
                init = initialize_vault(self.vault)
                if REPO_TELEGRAM_INDEX.is_file():
                    shutil.copy2(REPO_TELEGRAM_INDEX, init["telegram"])
                self.send_json({
                    "ok": True,
                    "state": scan_vault(
                        self.vault,
                        self.preview_index,
                        self.text_effect_preview_index,
                        self.text_bubble_preview_index,
                        self.text_template_preview_index,
                        self.font_preview_index,
                    ),
                })
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "Unknown endpoint")
        except Exception as error:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))

    def do_PATCH(self):
        parsed = urllib.parse.urlparse(self.path)
        if not parsed.path.startswith("/api/asset/"):
            self.send_error_json(HTTPStatus.NOT_FOUND, "Unknown endpoint")
            return
        asset_id = urllib.parse.unquote(parsed.path[len("/api/asset/"):])
        try:
            payload = self.read_json_body()
            self.send_json({
                "ok": True,
                "state": patch_asset(self.vault, asset_id, payload),
            })
        except Exception as error:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))

    def serve_static(self, request_path: str):
        relative = "index.html" if request_path in ("", "/") else request_path.lstrip("/")
        target = (STATIC_ROOT / relative).resolve()
        if STATIC_ROOT.resolve() not in target.parents and target != STATIC_ROOT.resolve():
            self.send_error_json(HTTPStatus.FORBIDDEN, "Invalid path")
            return
        if not target.is_file():
            self.send_error_json(HTTPStatus.NOT_FOUND, "Not found")
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in (
            "application/javascript",
            "application/json",
        ):
            content_type += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--scan-on-start", action="store_true")
    parser.add_argument("--preview-index", type=Path, default=DEFAULT_PREVIEW_INDEX)
    parser.add_argument(
        "--text-effect-preview-index",
        type=Path,
        default=DEFAULT_TEXT_EFFECT_PREVIEW_INDEX,
    )
    parser.add_argument(
        "--text-bubble-preview-index",
        type=Path,
        default=DEFAULT_TEXT_BUBBLE_PREVIEW_INDEX,
    )
    parser.add_argument(
        "--text-template-preview-index",
        type=Path,
        default=DEFAULT_TEXT_TEMPLATE_PREVIEW_INDEX,
    )
    parser.add_argument(
        "--font-preview-index",
        type=Path,
        default=DEFAULT_FONT_PREVIEW_INDEX,
    )
    parser.add_argument("--open", action="store_true")
    return parser


def main():
    args = build_parser().parse_args()
    vault = args.vault.expanduser().resolve()
    preview_index = args.preview_index.expanduser().resolve()
    text_effect_preview_index = (
        args.text_effect_preview_index.expanduser().resolve()
    )
    text_bubble_preview_index = (
        args.text_bubble_preview_index.expanduser().resolve()
    )
    text_template_preview_index = (
        args.text_template_preview_index.expanduser().resolve()
    )
    font_preview_index = args.font_preview_index.expanduser().resolve()
    initialize_vault(vault)
    if args.scan_on_start:
        print("scanning asset vault...")
        state = scan_vault(
            vault,
            preview_index,
            text_effect_preview_index,
            text_bubble_preview_index,
            text_template_preview_index,
            font_preview_index,
        )
        print(json.dumps(state["summary"], ensure_ascii=False, indent=2))
    DashboardHandler.vault = vault
    DashboardHandler.preview_index = preview_index
    DashboardHandler.text_effect_preview_index = text_effect_preview_index
    DashboardHandler.text_bubble_preview_index = text_bubble_preview_index
    DashboardHandler.text_template_preview_index = text_template_preview_index
    DashboardHandler.font_preview_index = font_preview_index
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"Asset dashboard: {url}")
    print(f"Vault: {vault}")
    if args.open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
