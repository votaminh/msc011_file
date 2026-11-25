#!/usr/bin/env python3
"""Upload/download CapCut text-animation ZIPs through the Telegram Bot API.

The bot token is read only from TELEGRAM_BOT_TOKEN and is never written to the
index. The generated JSON stores the catalog fields plus Telegram file_id and
file_unique_id so later downloads can call getFile without uploading again.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


API_ROOT = "https://api.telegram.org"


def api_request(token: str, method: str, payload: dict | None = None):
    url = f"{API_ROOT}/bot{token}/{method}"
    body = None
    headers = {}
    if payload is not None:
        body = urllib.parse.urlencode(payload).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", "replace")
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            raise RuntimeError(f"Telegram HTTP {error.code}: {raw}") from error
    if not result.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {result}")
    return result["result"]


def send_document(token: str, chat_id: str, path: Path, caption: str):
    boundary = f"----capcut-{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    def add_field(name: str, value: str):
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            value.encode(),
            b"\r\n",
        ])

    add_field("chat_id", chat_id)
    add_field("caption", caption[:1024])
    add_field("disable_content_type_detection", "false")
    mime = mimetypes.guess_type(path.name)[0] or "application/zip"
    chunks.extend([
        f"--{boundary}\r\n".encode(),
        (
            f'Content-Disposition: form-data; name="document"; '
            f'filename="{path.name}"\r\n'
        ).encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        path.read_bytes(),
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    request = urllib.request.Request(
        f"{API_ROOT}/bot{token}/sendDocument",
        data=b"".join(chunks),
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    result = None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                result = json.load(response)
            break
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", "replace")
            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                result = None
            if error.code == 429 or error.code >= 500:
                retry = 2 ** attempt
                parameters = (result or {}).get("parameters") or {}
                retry = int(parameters.get("retry_after") or retry)
                time.sleep(retry)
                continue
            raise RuntimeError(f"Telegram HTTP {error.code}: {raw}") from error
        except (urllib.error.URLError, TimeoutError):
            if attempt == 5:
                raise
            time.sleep(2 ** attempt)
    if result is None:
        raise RuntimeError("Telegram sendDocument returned no result")
    if not result.get("ok"):
        raise RuntimeError(f"Telegram sendDocument failed: {result}")
    return result["result"]


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


def resolve_assets(
    catalog_path: Path,
    asset_dirs: list[Path],
) -> tuple[list[dict], list[dict]]:
    catalog = load_json(catalog_path, None)
    if not isinstance(catalog, dict) or not isinstance(catalog.get("items"), list):
        raise ValueError(f"Invalid catalog: {catalog_path}")

    resolved: list[dict] = []
    missing: list[dict] = []
    seen_ids: set[str] = set()
    seen_files: set[str] = set()
    for item in catalog["items"]:
        effect_id = str(item.get("effectId") or "").strip()
        asset_value = str(item.get("asset") or "").strip()
        name = str(item.get("name") or "").strip()
        category = str(item.get("category") or "").strip()
        if not effect_id or not asset_value or effect_id in seen_ids:
            continue
        seen_ids.add(effect_id)
        file_name = Path(asset_value).name
        path = next(
            (directory / file_name for directory in asset_dirs
             if (directory / file_name).is_file()),
            None,
        )
        if path is None:
            missing.append({
                "effectId": effect_id,
                "name": name,
                "file": file_name,
            })
            continue
        seen_files.add(file_name)
        resolved.append({
            "category": category,
            "name": name,
            "effectId": effect_id,
            "resourceId": str(item.get("resourceId") or effect_id),
            "asset": file_name,
            "source": str(path),
            "bytes": path.stat().st_size,
        })
    return resolved, missing


def command_verify(args):
    resolved, missing = resolve_assets(
        args.catalog,
        [args.asset_dir, args.fallback_dir] if args.fallback_dir else [args.asset_dir],
    )
    print(f"catalog_items={len(resolved) + len(missing)}")
    print(f"resolved={len(resolved)}")
    print(f"missing={len(missing)}")
    print(f"over_50mb={sum(1 for item in resolved if item['bytes'] > 50 * 1024 * 1024)}")
    for item in missing[:50]:
        print(f"MISSING {item['effectId']} {item['name']} {item['file']}")
    return 1 if missing else 0


def command_chat_id(args):
    token = require_token()
    updates = api_request(token, "getUpdates", {"limit": 100})
    chats = {}
    for update in updates:
        message = update.get("message") or update.get("channel_post") or {}
        chat = message.get("chat") or {}
        if chat.get("id") is not None:
            chats[str(chat["id"])] = {
                "id": chat["id"],
                "type": chat.get("type"),
                "title": chat.get("title"),
                "username": chat.get("username"),
                "first_name": chat.get("first_name"),
            }
    print(json.dumps(list(chats.values()), ensure_ascii=False, indent=2))
    return 0 if chats else 2


def command_upload(args):
    token = require_token()
    if not args.chat_id:
        raise SystemExit("Set TELEGRAM_CHAT_ID or pass --chat-id")
    resolved, missing = resolve_assets(
        args.catalog,
        [args.asset_dir, args.fallback_dir] if args.fallback_dir else [args.asset_dir],
    )
    if missing:
        raise SystemExit(
            f"Missing {len(missing)} assets; run verify and merge fallback first"
        )

    previous = load_json(args.index, {"version": 1, "items": []})
    uploaded = {
        item["effectId"]: item
        for item in previous.get("items", [])
        if item.get("file_id")
    }
    index = {"version": 1, "chat_id": str(args.chat_id), "items": []}
    manifest = {
        "catalog": str(args.catalog),
        "asset_dirs": [str(args.asset_dir)]
        + ([str(args.fallback_dir)] if args.fallback_dir else []),
    }
    index["manifest"] = manifest

    for position, item in enumerate(resolved, 1):
        existing = uploaded.get(item["effectId"])
        if existing and existing.get("bytes") == item["bytes"]:
            index["items"].append(existing)
            print(f"[{position}/{len(resolved)}] skip {item['effectId']}")
            continue
        path = Path(item["source"])
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        caption = (
            f"{item['category']} | {item['name']} | {item['effectId']}"
        )
        while True:
            try:
                message = send_document(token, str(args.chat_id), path, caption)
                break
            except RuntimeError as error:
                if "retry after" not in str(error).lower():
                    raise
                time.sleep(10)
        document = message.get("document") or {}
        record = {
            key: item[key]
            for key in ("category", "name", "effectId", "resourceId", "asset", "bytes")
        }
        record.update({
            "sha256": digest,
            "file_id": document.get("file_id"),
            "file_unique_id": document.get("file_unique_id"),
            "message_id": message.get("message_id"),
            "telegram_file_name": document.get("file_name"),
        })
        index["items"].append(record)
        atomic_json(args.index, index)
        print(
            f"[{position}/{len(resolved)}] upload {item['effectId']} "
            f"{item['name']} -> {record['file_id']}"
        )
        time.sleep(args.delay)


def normalized_zip_name(name: str) -> str:
    base = Path(name or "").name
    if base.lower().endswith(".zip") and "(" in base:
        stem = base[:-4]
        base = stem.split("(", 1)[0].strip() + ".zip"
    return base


def command_scan(args):
    token = require_token()
    resolved, missing = resolve_assets(
        args.catalog,
        [args.asset_dir, args.fallback_dir] if args.fallback_dir else [args.asset_dir],
    )
    if missing:
        raise SystemExit(f"Catalog has {len(missing)} missing assets")

    by_id = {item["effectId"]: item for item in resolved}
    by_file = {item["asset"]: item for item in resolved}
    previous = load_json(args.index, {"version": 1, "items": []})
    records = {
        str(item.get("effectId")): item
        for item in previous.get("items", [])
        if item.get("effectId")
    }
    offset = int(previous.get("next_update_id") or 0)
    scanned = 0
    matched = 0

    while True:
        updates = api_request(token, "getUpdates", {
            "offset": offset,
            "limit": 100,
            "timeout": 0,
            "allowed_updates": json.dumps(["message", "channel_post"]),
        })
        if not updates:
            break
        batch_last = offset - 1
        for update in updates:
            update_id = int(update.get("update_id") or 0)
            batch_last = max(batch_last, update_id)
            message = (
                update.get("message")
                or update.get("channel_post")
                or update.get("edited_message")
                or {}
            )
            document = message.get("document") or {}
            file_name = normalized_zip_name(document.get("file_name") or "")
            if not file_name.lower().endswith(".zip"):
                continue
            scanned += 1
            effect_id = Path(file_name).stem if Path(file_name).stem.isdigit() else ""
            catalog_item = by_id.get(effect_id) or by_file.get(file_name)
            record = {
                "category": catalog_item.get("category") if catalog_item else "",
                "name": catalog_item.get("name") if catalog_item else "",
                "effectId": catalog_item.get("effectId") if catalog_item else effect_id,
                "resourceId": (
                    catalog_item.get("resourceId")
                    if catalog_item else effect_id
                ),
                "asset": catalog_item.get("asset") if catalog_item else file_name,
                "bytes": document.get("file_size"),
                "file_id": document.get("file_id"),
                "file_unique_id": document.get("file_unique_id"),
                "message_id": message.get("message_id"),
                "telegram_file_name": document.get("file_name"),
                "date": message.get("date"),
                "caption": message.get("caption") or "",
                "matched": bool(catalog_item),
            }
            key = record["effectId"] or file_name
            records[key] = record
            if catalog_item:
                matched += 1
        offset = batch_last + 1
        atomic_json(args.index, {
            "version": 1,
            "next_update_id": offset,
            "catalog": str(args.catalog),
            "items": list(records.values()),
        })
        print(
            f"scanned={scanned} matched={matched} "
            f"indexed={len(records)} next_update_id={offset}"
        )
        if len(updates) < 100:
            break

    index = load_json(args.index, {"version": 1, "items": []})
    index["next_update_id"] = offset
    index["catalog"] = str(args.catalog)
    index["items"] = list(records.values())
    atomic_json(args.index, index)
    print(
        f"PASS scanned={scanned} matched={matched} "
        f"indexed={len(records)} next_update_id={offset}"
    )


def command_download(args):
    token = require_token()
    index = load_json(args.index, None)
    if not isinstance(index, dict):
        raise SystemExit(f"Invalid index: {args.index}")
    selected = index.get("items", [])
    if args.effect_id:
        wanted = set(args.effect_id)
        selected = [item for item in selected if item.get("effectId") in wanted]
    args.output.mkdir(parents=True, exist_ok=True)
    for position, item in enumerate(selected, 1):
        file_id = item.get("file_id")
        if not file_id:
            continue
        target = args.output / item.get("asset", f"{item['effectId']}.zip")
        if target.is_file() and target.stat().st_size == item.get("bytes"):
            print(f"[{position}/{len(selected)}] skip {target.name}")
            continue
        info = api_request(token, "getFile", {"file_id": file_id})
        file_path = info.get("file_path")
        if not file_path:
            raise RuntimeError(f"No file_path for {file_id}")
        url = f"{API_ROOT}/file/bot{token}/{file_path}"
        temporary = target.with_suffix(target.suffix + ".part")
        urllib.request.urlretrieve(url, temporary)
        temporary.replace(target)
        print(f"[{position}/{len(selected)}] download {target.name}")
        time.sleep(args.delay)


def require_token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")
    return token


def build_parser():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--catalog", type=Path, required=True)
    verify.add_argument("--asset-dir", type=Path, required=True)
    verify.add_argument("--fallback-dir", type=Path)
    verify.set_defaults(func=command_verify)

    chat_id = subparsers.add_parser("chat-id")
    chat_id.set_defaults(func=command_chat_id)

    upload = subparsers.add_parser("upload")
    upload.add_argument("--catalog", type=Path, required=True)
    upload.add_argument("--asset-dir", type=Path, required=True)
    upload.add_argument("--fallback-dir", type=Path)
    upload.add_argument("--index", type=Path, required=True)
    upload.add_argument("--chat-id", default=os.environ.get("TELEGRAM_CHAT_ID"))
    upload.add_argument("--delay", type=float, default=1.2)
    upload.set_defaults(func=command_upload)

    download = subparsers.add_parser("download")
    download.add_argument("--index", type=Path, required=True)
    download.add_argument("--output", type=Path, required=True)
    download.add_argument("--effect-id", action="append")
    download.add_argument("--delay", type=float, default=0.2)
    download.set_defaults(func=command_download)

    scan = subparsers.add_parser("scan")
    scan.add_argument("--catalog", type=Path, required=True)
    scan.add_argument("--asset-dir", type=Path, required=True)
    scan.add_argument("--fallback-dir", type=Path)
    scan.add_argument("--index", type=Path, required=True)
    scan.set_defaults(func=command_scan)
    return parser


def main():
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except (RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
