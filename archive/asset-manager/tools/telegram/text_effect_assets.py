#!/usr/bin/env python3
"""Prefetch and upload unique Text Effects ZIPs through the Telegram Bot API."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from text_animation_assets import (
    api_request,
    atomic_json,
    load_json,
    require_token,
    send_document,
)


USER_AGENT = "CapCut-Android/20.0.0"
FILE_URL_PATTERN = re.compile(r"url_list=\[([^\]]+)\]")
RETRY_AFTER_PATTERN = re.compile(r"retry after (\d+)", re.IGNORECASE)


def effect_url(record: dict) -> str:
    raw = (record.get("effect") or {}).get("fileUrlRaw") or ""
    match = FILE_URL_PATTERN.search(raw)
    if not match:
        return ""
    value = match.group(1).split(",", 1)[0].strip()
    return value if value.startswith(("http://", "https://")) else ""


def unique_effects(runtime: dict) -> dict[str, dict]:
    result = {}
    for record in runtime.get("effects", []):
        effect = record.get("effect") or {}
        effect_id = str(effect.get("effectId") or "")
        if not effect_id:
            continue
        current = result.get(effect_id)
        if current is None or (
            not effect_url(current) and effect_url(record)
        ):
            result[effect_id] = record
    return result


def download_asset(record: dict, output: Path) -> dict:
    effect = record.get("effect") or {}
    effect_id = str(effect.get("effectId") or "")
    category = record.get("category") or {}
    url = effect_url(record)
    if not url:
        raise ValueError("missing file URL")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        status = response.getcode()
        if status != 200:
            raise RuntimeError(f"HTTP {status}")
        payload = response.read()
    if not zipfile.is_zipfile(__import__("io").BytesIO(payload)):
        raise ValueError("response is not a ZIP")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(output)
    return {
        "effectId": effect_id,
        "resourceId": effect.get("resourceId") or effect_id,
        "name": effect.get("name") or effect_id,
        "categoryId": category.get("id") or "",
        "categoryName": category.get("name") or "",
        "asset": output.name,
        "path": str(output),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "sourceUrl": url,
    }


def command_verify(args):
    runtime = load_json(args.runtime, {})
    effects = unique_effects(runtime)
    missing = [
        effect_id for effect_id, record in effects.items()
        if not effect_url(record)
    ]
    print(f"unique_effects={len(effects)} missing_url={len(missing)}")
    return 1 if missing else 0


def command_prefetch(args):
    runtime = load_json(args.runtime, {})
    effects = unique_effects(runtime)
    assets = load_json(args.assets_index, {"version": 1, "items": []})
    existing = {
        item["effectId"]: item
        for item in assets.get("items", [])
        if item.get("effectId")
    }
    failures = []

    def process(effect_id: str, record: dict):
        try:
            output = args.asset_dir / f"{effect_id}.zip"
            item = existing.get(effect_id)
            if item and output.is_file() and output.stat().st_size == item.get("bytes"):
                return item, None
            return download_asset(record, output), None
        except Exception as error:
            return None, {
                "effectId": effect_id,
                "error": f"{type(error).__name__}: {error}",
            }

    with concurrent.futures.ThreadPoolExecutor(
            max_workers=args.workers) as pool:
        futures = {
            pool.submit(process, effect_id, record): effect_id
            for effect_id, record in effects.items()
        }
        for index, future in enumerate(
                concurrent.futures.as_completed(futures), 1):
            item, failure = future.result()
            if item:
                existing[item["effectId"]] = item
            if failure:
                failures.append(failure)
            if index % 25 == 0 or index == len(futures):
                atomic_json(args.assets_index, {
                    "version": 1,
                    "runtime": str(args.runtime),
                    "items": list(existing.values()),
                    "failures": failures,
                })
                print(
                    f"{index}/{len(futures)} assets={len(existing)} "
                    f"failures={len(failures)}",
                    flush=True,
                )
    return 0 if not failures else 1


def command_upload(args):
    token = require_token()
    if not args.chat_id:
        raise SystemExit("Set TELEGRAM_CHAT_ID or pass --chat-id")
    assets = load_json(args.assets_index, {"version": 1, "items": []})
    source = {
        item["effectId"]: item
        for item in assets.get("items", [])
        if item.get("effectId")
    }
    previous = load_json(args.index, {"version": 1, "items": []})
    uploaded = {
        item["effectId"]: item
        for item in previous.get("items", [])
        if item.get("file_id")
    }
    pending = [
        (effect_id, item)
        for effect_id, item in source.items()
        if effect_id not in uploaded
    ]
    gate = threading.Lock()
    retry_until = [0.0]

    def wait_for_gate():
        while True:
            with gate:
                remaining = retry_until[0] - time.time()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 5))

    def upload_one(effect_id: str, item: dict):
        path = Path(item["path"])
        if not path.is_file():
            return effect_id, None, f"missing local asset: {path}"
        caption = f"{item['name']} | {effect_id}"
        last_error = None
        for _attempt in range(5):
            wait_for_gate()
            try:
                result = send_document(token, str(args.chat_id), path, caption)
                document = result.get("document") or {}
                record = {
                    **{key: value for key, value in item.items()
                       if key != "sourceUrl"},
                    "file_id": document.get("file_id"),
                    "file_unique_id": document.get("file_unique_id"),
                    "message_id": result.get("message_id"),
                    "chat_id": str(args.chat_id),
                    "telegram_file_name": document.get("file_name") or path.name,
                }
                return effect_id, record, None
            except Exception as error:
                last_error = error
                match = RETRY_AFTER_PATTERN.search(str(error))
                if not match:
                    break
                delay = int(match.group(1)) + 3
                with gate:
                    retry_until[0] = max(
                        retry_until[0], time.time() + delay)
                print(
                    f"rate-limit wait={delay}s effect={effect_id}",
                    flush=True,
                )
        return effect_id, None, f"{type(last_error).__name__}: {last_error}"

    failures = []
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=args.workers) as pool:
        futures = [
            pool.submit(upload_one, effect_id, item)
            for effect_id, item in pending
        ]
        for index, future in enumerate(
                concurrent.futures.as_completed(futures), 1):
            effect_id, record, failure = future.result()
            if record:
                uploaded[effect_id] = record
            if failure:
                failures.append({"effectId": effect_id, "error": failure})
            if index % 2 == 0 or index == len(futures):
                atomic_json(args.index, {
                    "version": 1,
                    "runtime": str(args.runtime),
                    "items": list(uploaded.values()),
                    "failures": failures,
                })
            print(
                f"{index}/{len(futures)} total_uploaded={len(uploaded)} "
                f"failures={len(failures)} {effect_id}",
                flush=True,
            )
    print(
        f"PASS uploaded={len(uploaded)}/{len(source)} "
        f"failures={len(failures)} index={args.index}"
    )
    return 0 if not failures else 1


def build_parser():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--runtime",
        type=Path,
        default=Path(
            "/Users/votaminh99/Documents/Default Project/demo_andorid/"
            "asset-vault/runtime/text-effects-runtime.json"
        ),
    )
    common.add_argument(
        "--asset-dir",
        type=Path,
        default=Path(
            "/Users/votaminh99/Documents/Default Project/demo_andorid/"
            "asset-vault/text-effects/assets"
        ),
    )
    common.add_argument(
        "--assets-index",
        type=Path,
        default=Path(
            "/Users/votaminh99/Documents/Default Project/demo_andorid/"
            "asset-vault/text-effects/assets.json"
        ),
    )

    verify = sub.add_parser("verify", parents=[common])
    verify.set_defaults(func=command_verify)
    prefetch = sub.add_parser("prefetch", parents=[common])
    prefetch.add_argument("--workers", type=int, default=8)
    prefetch.set_defaults(func=command_prefetch)
    upload = sub.add_parser("upload", parents=[common])
    upload.add_argument("--index", type=Path, required=True)
    upload.add_argument("--chat-id", default=os.environ.get("TELEGRAM_CHAT_ID"))
    upload.add_argument("--workers", type=int, default=4)
    upload.set_defaults(func=command_upload)
    return parser


def main():
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
