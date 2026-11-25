#!/usr/bin/env python3
"""Prepare and upload a small Text Template demo set through Telegram."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import io
import json
import re
import time
import urllib.request
import zipfile
from pathlib import Path

from text_animation_assets import (
    api_request,
    atomic_json,
    load_json,
    send_document,
)


USER_AGENT = "CapCut-Android/20.0.0"
FILE_URL = re.compile(r"file_url=UrlModel\(url_list=\[([^\]]*)\]", re.S)
ICON_URL = re.compile(r"icon_url=UrlModel\(url_list=\[([^\]]*)\]", re.S)
ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "asset-vault/runtime/text-templates-runtime.json"
DEMO = ROOT / "demo-upload/text-templates"
MANIFEST = DEMO / "manifest.json"
INDEX = ROOT / "tools/telegram/text-templates-telegram-index.json"
DEPENDENCY_MANIFEST = DEMO / "dependencies/manifest.json"
DEPENDENCY_INDEX = (
    ROOT / "tools/telegram/text-template-dependencies-telegram-index.json"
)


def first_url(pattern, raw):
    match = pattern.search(raw or "")
    if not match:
        return ""
    value = match.group(1).split(",", 1)[0].strip()
    return value if value.startswith(("http://", "https://")) else ""


def candidate(row):
    effect = row.get("effect") or {}
    extra = json.loads(effect.get("extra") or "{}")
    sdk = json.loads(effect.get("sdkExtra") or "{}")
    raw = effect.get("raw") or ""
    return {
        "effectId": str(effect.get("effectId") or ""),
        "resourceId": str(effect.get("resourceId") or ""),
        "name": effect.get("name") or "",
        "categoryId": (row.get("category") or {}).get("id") or "",
        "categoryName": (row.get("category") or {}).get("name") or "",
        "previewTimeMs": int(extra.get("static_preview_time") or 0),
        "vip": bool(extra.get("is_vip")),
        "dependencies": sdk.get("depend_resource_list") or [],
        "fileUrl": first_url(FILE_URL, raw),
        "iconUrl": first_url(ICON_URL, raw),
    }


def read_token(path):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    token = values.get("telegramBotToken")
    if not token:
        raise SystemExit(f"telegramBotToken not found in {path}")
    return token


def download(url, output):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        if response.getcode() != 200:
            raise RuntimeError(f"HTTP {response.getcode()}")
        data = response.read()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(output)
    return data


def command_prepare(args):
    runtime = load_json(args.runtime, {})
    selected = []
    seen_categories = set()
    seen_effects = set()
    for row in runtime.get("templates", []):
        item = candidate(row)
        if (not args.include_vip and item["vip"]) \
                or not item["fileUrl"] or not item["iconUrl"]:
            continue
        if item["effectId"] in seen_effects:
            continue
        if not args.all and item["categoryName"] in seen_categories:
            continue
        if len(item["dependencies"]) > args.max_dependencies:
            continue
        if not args.all:
            seen_categories.add(item["categoryName"])
        seen_effects.add(item["effectId"])
        selected.append(item)
        if not args.all and len(selected) >= args.limit:
            break
    if not args.all and len(selected) < args.limit:
        raise SystemExit(
            f"Only found {len(selected)} candidates; need {args.limit}")

    def prepare_one(item):
        effect_id = item["effectId"]
        zip_path = DEMO / "assets" / f"{effect_id}.zip"
        icon_path = DEMO / "previews" / f"{effect_id}.webp"
        if zip_path.is_file() and zip_path.stat().st_size > 0:
            zip_bytes = zip_path.read_bytes()
        else:
            zip_bytes = download(item["fileUrl"], zip_path)
        if not zipfile.is_zipfile(io.BytesIO(zip_bytes)):
            raise RuntimeError(f"{effect_id}: downloaded data is not a ZIP")
        if not icon_path.is_file() or icon_path.stat().st_size == 0:
            download(item["iconUrl"], icon_path)
        item.update({
            "asset": zip_path.name,
            "path": str(zip_path),
            "bytes": len(zip_bytes),
            "sha256": hashlib.sha256(zip_bytes).hexdigest(),
            "preview": str(icon_path),
        })
        return item

    items = []
    failures = []
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(prepare_one, item) for item in selected]
        for index, future in enumerate(
                concurrent.futures.as_completed(futures), 1):
            try:
                item = future.result()
                items.append(item)
            except Exception as error:
                failures.append(str(error))
            if index % 50 == 0 or index == len(futures):
                print(
                    f"{index}/{len(futures)} ready={len(items)}"
                    f" failures={len(failures)}",
                    flush=True,
                )
    items.sort(key=lambda item: item["effectId"])

    atomic_json(args.manifest, {
        "version": 1,
        "source": "CapCut 20.0.0 text-template runtime",
        "runtime": str(args.runtime),
        "items": items,
    })
    print(f"manifest={args.manifest} items={len(items)}")
    if failures:
        print(f"prepare failures={len(failures)}")
        for failure in failures[:50]:
            print(f"failure: {failure}")
        return 1
    return 0


def command_verify(args):
    manifest = load_json(args.manifest, {})
    items = manifest.get("items", [])
    failures = []
    for item in items:
        path = Path(item.get("path") or "")
        if not path.is_file():
            failures.append({"effectId": item.get("effectId"),
                             "error": "missing zip"})
            continue
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != item.get("sha256"):
            failures.append({"effectId": item.get("effectId"),
                             "error": "sha256 mismatch"})
        if not zipfile.is_zipfile(io.BytesIO(data)):
            failures.append({"effectId": item.get("effectId"),
                             "error": "invalid zip"})
    print(f"items={len(items)} failures={len(failures)}")
    if failures:
        print(json.dumps(failures, ensure_ascii=False, indent=2))
        return 1
    return 0


def command_upload(args):
    token = read_token(args.token_file)
    manifest = load_json(args.manifest, {})
    index = load_json(args.index, {"version": 1, "items": []})
    uploaded = {
        str(item.get("effectId")): item
        for item in index.get("items", [])
        if item.get("file_id")
    }
    pending = [
        item for item in manifest.get("items", [])
        if str(item["effectId"]) not in uploaded
    ]

    def upload_one(item):
        effect_id = str(item["effectId"])
        path = Path(item["path"])
        result = send_document(
            token,
            str(args.chat_id),
            path,
            f"{item['name']} | {item['categoryName']} | {effect_id}",
        )
        document = result.get("document") or {}
        record = {
            **{key: value for key, value in item.items()
               if key not in {"fileUrl", "iconUrl"}},
            "file_id": document.get("file_id"),
            "file_unique_id": document.get("file_unique_id"),
            "message_id": result.get("message_id"),
            "chat_id": str(args.chat_id),
            "telegram_file_name": document.get("file_name") or path.name,
        }
        return effect_id, record

    with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, args.workers)) as pool:
        failures = 0
        completed = 0
        for start in range(0, len(pending), 50):
            futures = []
            for item in pending[start:start + 50]:
                futures.append(pool.submit(upload_one, item))
                time.sleep(args.delay)
            for future in concurrent.futures.as_completed(futures):
                completed += 1
                try:
                    effect_id, record = future.result()
                    uploaded[effect_id] = record
                    atomic_json(args.index, {
                        "version": 1,
                        "items": list(uploaded.values()),
                    })
                    print(
                        f"[{completed}/{len(pending)}] uploaded {effect_id}"
                        f" {record['file_id']}",
                        flush=True,
                    )
                except Exception as error:
                    failures += 1
                    print(
                        f"[{completed}/{len(pending)}] failed {error}",
                        flush=True,
                    )
        print(
            f"upload complete={len(pending) - failures}"
            f" failed={failures} total_index={len(uploaded)}",
            flush=True,
        )


def command_upload_dependencies(args):
    token = read_token(args.token_file)
    manifest = load_json(args.manifest, {})
    index = load_json(args.index, {"version": 1, "items": []})
    uploaded = {
        str(item["key"]): item
        for item in index.get("items", [])
        if item.get("file_id") and item.get("key")
    }
    seen = set()
    position = 0
    for template in manifest.get("items", []):
        for dependency in template.get("dependencies", []):
            panel = str(dependency.get("panel", ""))
            resource_id = str(dependency.get("resourceId", ""))
            file_hash = str(dependency.get("fileHash", ""))
            key = f"{panel}|{resource_id}"
            if not panel or not resource_id or not file_hash or key in seen:
                continue
            seen.add(key)
            position += 1
            if dependency.get("fileId"):
                uploaded[key] = {
                    "key": key,
                    "panel": panel,
                    "resourceId": resource_id,
                    "fileId": dependency["fileId"],
                }
                continue
            if key in uploaded:
                dependency["fileId"] = uploaded[key]["fileId"]
                continue
            path = args.assets / panel / resource_id / f"{file_hash}.zip"
            if not path.is_file():
                print(f"[{position}] missing {key} {path}", flush=True)
                continue
            data = path.read_bytes()
            sha256 = hashlib.sha256(data).hexdigest()
            result = send_document(
                token,
                str(args.chat_id),
                path,
                f"text-template-dependency | {panel} | "
                f"{resource_id} | {file_hash}",
            )
            document = result.get("document") or {}
            file_id = document.get("file_id")
            if not file_id:
                raise RuntimeError(f"{key}: Telegram returned no file_id")
            dependency.update({
                "fileId": file_id,
                "bytes": len(data),
                "sha256": sha256,
            })
            record = {
                "key": key,
                "panel": panel,
                "resourceId": resource_id,
                "fileHash": file_hash,
                "fileId": file_id,
                "fileUniqueId": document.get("file_unique_id"),
                "messageId": result.get("message_id"),
                "chatId": str(args.chat_id),
                "bytes": len(data),
                "sha256": sha256,
            }
            uploaded[key] = record
            atomic_json(args.index, {
                "version": 1,
                "items": list(uploaded.values()),
            })
            atomic_json(args.manifest, manifest)
            print(f"[{position}] uploaded {key} {file_id}", flush=True)
            time.sleep(args.delay)
    atomic_json(args.manifest, manifest)


def command_watch(args):
    token = read_token(args.token_file)
    manifest = load_json(args.manifest, {})
    by_id = {
        str(item.get("effectId")): item
        for item in manifest.get("items", [])
        if item.get("effectId")
    }
    index = load_json(args.index, {"version": 1, "items": []})
    records = {
        str(item.get("effectId")): item
        for item in index.get("items", [])
        if item.get("effectId")
    }
    offset = int(index.get("next_update_id") or 0)
    print(
        f"watch start chat={args.chat_id} offset={offset}"
        f" manifest={len(by_id)} indexed={len(records)}",
        flush=True,
    )
    while True:
        updates = api_request(token, "getUpdates", {
            "offset": offset,
            "limit": 100,
            "timeout": args.poll_timeout,
            "allowed_updates": json.dumps(["message", "channel_post"]),
        })
        if not updates:
            continue
        last = offset - 1
        changed = 0
        for update in updates:
            last = max(last, int(update.get("update_id") or 0))
            message = (
                update.get("message")
                or update.get("channel_post")
                or update.get("edited_message")
                or {}
            )
            chat = message.get("chat") or {}
            if str(chat.get("id")) != str(args.chat_id):
                continue
            document = message.get("document") or {}
            file_name = Path(document.get("file_name") or "").name
            if not file_name.lower().endswith(".zip"):
                continue
            effect_id = Path(file_name).stem
            item = by_id.get(effect_id)
            if item is None:
                print(
                    f"unmatched file={file_name}"
                    f" file_id={document.get('file_id')}",
                    flush=True,
                )
                continue
            record = {
                **{key: value for key, value in item.items()
                   if key not in {"fileUrl", "iconUrl"}},
                "file_id": document.get("file_id"),
                "file_unique_id": document.get("file_unique_id"),
                "message_id": message.get("message_id"),
                "chat_id": str(chat.get("id")),
                "telegram_file_name": document.get("file_name"),
                "date": message.get("date"),
                "caption": message.get("caption") or "",
                "matched": True,
            }
            records[effect_id] = record
            changed += 1
            print(
                f"matched {effect_id} file_id={record['file_id']}"
                f" indexed={len(records)}",
                flush=True,
            )
        offset = last + 1
        index = {
            "version": 1,
            "next_update_id": offset,
            "chat_id": str(args.chat_id),
            "items": list(records.values()),
        }
        atomic_json(args.index, index)
        if changed:
            print(
                f"batch matched={changed} indexed={len(records)}"
                f" offset={offset}",
                flush=True,
            )


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--runtime", type=Path, default=RUNTIME)
    prepare.add_argument("--manifest", type=Path, default=MANIFEST)
    prepare.add_argument("--limit", type=int, default=10)
    prepare.add_argument("--max-dependencies", type=int, default=32)
    prepare.add_argument("--all", action="store_true")
    prepare.add_argument("--include-vip", action="store_true")
    prepare.add_argument("--workers", type=int, default=12)
    prepare.set_defaults(func=command_prepare)

    verify = sub.add_parser("verify")
    verify.add_argument("--manifest", type=Path, default=MANIFEST)
    verify.set_defaults(func=command_verify)

    upload = sub.add_parser("upload")
    upload.add_argument("--manifest", type=Path, default=MANIFEST)
    upload.add_argument("--index", type=Path, default=INDEX)
    upload.add_argument("--chat-id", required=True)
    upload.add_argument("--token-file", type=Path, required=True)
    upload.add_argument("--delay", type=float, default=1.0)
    upload.add_argument("--workers", type=int, default=1)
    upload.set_defaults(func=command_upload)

    upload_dependencies = sub.add_parser("upload-dependencies")
    upload_dependencies.add_argument(
        "--manifest", type=Path, default=DEPENDENCY_MANIFEST)
    upload_dependencies.add_argument(
        "--assets", type=Path,
        default=DEPENDENCY_MANIFEST.parent / "assets")
    upload_dependencies.add_argument(
        "--index", type=Path, default=DEPENDENCY_INDEX)
    upload_dependencies.add_argument("--chat-id", required=True)
    upload_dependencies.add_argument("--token-file", type=Path, required=True)
    upload_dependencies.add_argument("--delay", type=float, default=1.0)
    upload_dependencies.set_defaults(func=command_upload_dependencies)

    watch = sub.add_parser("watch")
    watch.add_argument("--manifest", type=Path, default=MANIFEST)
    watch.add_argument("--index", type=Path, default=INDEX)
    watch.add_argument("--chat-id", required=True)
    watch.add_argument("--token-file", type=Path, required=True)
    watch.add_argument("--poll-timeout", type=int, default=30)
    watch.set_defaults(func=command_watch)

    args = parser.parse_args()
    result = args.func(args)
    raise SystemExit(result or 0)


if __name__ == "__main__":
    main()
