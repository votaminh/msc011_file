#!/usr/bin/env python3
"""Publish lightweight animation previews to the public msc011_file repo."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


USER_AGENT = "CapCut-Android/20.0.0"


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
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    return suffix or ".img"


def download(url: str) -> tuple[bytes, str, str]:
    if not url:
        raise ValueError("missing URL")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = response.read()
        content_type = response.headers.get("Content-Type", "")
    if not payload:
        raise ValueError("empty response")
    if payload[:64].lstrip().lower().startswith((b"<!doctype", b"<html")):
        raise ValueError("received HTML instead of image")
    return payload, content_type, sniff_extension(payload, content_type, url)


def valid_existing(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    with path.open("rb") as source:
        head = source.read(16)
    return (
        head.startswith((b"GIF87a", b"GIF89a", b"\x89PNG\r\n\x1a\n",
                         b"\xff\xd8\xff"))
        or (head.startswith(b"RIFF") and head[8:12] == b"WEBP")
    )


def fetch_missing(url: str, destination_dir: Path, effect_id: str,
                  role: str, overwrite: bool):
    for suffix in (".awebp", ".webp", ".gif", ".image", ".png", ".jpg", ".img"):
        candidate = destination_dir / f"{effect_id}-{role}{suffix}"
        if not overwrite and valid_existing(candidate):
            payload = candidate.read_bytes()
            return candidate, payload, hashlib.sha256(payload).hexdigest()
    last_error = None
    for attempt in range(3):
        try:
            payload, _content_type, extension = download(url)
            destination = destination_dir / f"{effect_id}-{role}{extension}"
            temporary = destination.with_suffix(destination.suffix + ".part")
            temporary.write_bytes(payload)
            temporary.replace(destination)
            return destination, payload, hashlib.sha256(payload).hexdigest()
        except Exception as error:  # noqa: BLE001
            last_error = f"{type(error).__name__}: {error}"
            time.sleep(1 + attempt)
    raise RuntimeError(last_error or "download failed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--telegram-index", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument(
        "--raw-base",
        default="https://raw.githubusercontent.com/votaminh/msc011_file/main",
    )
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    source = load_json(args.source, {})
    items = [
        item
        for group in source.get("categories", {}).values()
        for item in group.get("items", [])
    ]
    telegram_index = load_json(args.telegram_index, {"items": []})
    telegram = {
        str(item.get("effectId")): item
        for item in telegram_index.get("items", [])
        if item.get("file_id")
    }
    animation_dir = args.repo / "previews/text-animations/animations"
    thumb_dir = args.repo / "previews/text-animations/thumbs"
    animation_dir.mkdir(parents=True, exist_ok=True)
    thumb_dir.mkdir(parents=True, exist_ok=True)

    def process(item):
        effect_id = str(item.get("effectId") or "").strip()
        if not effect_id:
            return None, {"effectId": effect_id, "error": "missing effectId"}
        animated_url = ((item.get("iconUrl") or {}).get("urls") or [None])[0]
        thumb_url = item.get("staticCoverUrl") or animated_url
        try:
            animated_path, animated_bytes, animated_sha = fetch_missing(
                animated_url, animation_dir, effect_id, "anim", args.overwrite)
            thumb_path, thumb_bytes, thumb_sha = fetch_missing(
                thumb_url, thumb_dir, effect_id, "thumb", args.overwrite)
        except Exception as error:  # noqa: BLE001
            return None, {
                "effectId": effect_id,
                "name": item.get("name"),
                "error": str(error),
            }
        record = {
            "effectId": effect_id,
            "resourceId": str(item.get("resourceId") or effect_id),
            "name": str(item.get("name") or ""),
            "category": str(item.get("category") or ""),
            "preview": {
                "path": str(animated_path.relative_to(args.repo)),
                "rawUrl": (
                    args.raw_base.rstrip("/") + "/"
                    + str(animated_path.relative_to(args.repo)).replace(os.sep, "/")
                ),
                "bytes": len(animated_bytes),
                "sha256": animated_sha,
            },
            "thumb": {
                "path": str(thumb_path.relative_to(args.repo)),
                "rawUrl": (
                    args.raw_base.rstrip("/") + "/"
                    + str(thumb_path.relative_to(args.repo)).replace(os.sep, "/")
                ),
                "bytes": len(thumb_bytes),
                "sha256": thumb_sha,
            },
            "telegram": {
                "fileId": telegram.get(effect_id, {}).get("file_id"),
                "fileUniqueId": telegram.get(effect_id, {}).get("file_unique_id"),
                "asset": telegram.get(effect_id, {}).get("asset"),
                "bytes": telegram.get(effect_id, {}).get("bytes"),
            },
        }
        return record, None

    records = []
    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(process, item) for item in items]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            record, failure = future.result()
            if record:
                records.append(record)
            if failure:
                failures.append(failure)
            if index % 25 == 0 or index == len(futures):
                print(
                    f"{index}/{len(futures)} previews={len(records)} "
                    f"failures={len(failures)}",
                    flush=True,
                )

    records.sort(key=lambda item: (
        {"In": 0, "Out": 1, "Loop": 2}.get(item["category"], 9),
        item["name"].lower(),
    ))
    index = {
        "schemaVersion": 1,
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "rawBase": args.raw_base.rstrip("/"),
        "source": str(args.source),
        "count": len(records),
        "totalPreviewBytes": sum(item["preview"]["bytes"] for item in records),
        "totalThumbBytes": sum(item["thumb"]["bytes"] for item in records),
        "items": records,
        "failures": failures,
    }
    output = args.repo / "text-animation-previews.json"
    atomic_json(output, index)
    print(f"PASS index={output} count={len(records)} failures={len(failures)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
