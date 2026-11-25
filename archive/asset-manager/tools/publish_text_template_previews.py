#!/usr/bin/env python3
"""Publish CapCut text-template preview images to msc011_file."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import urllib.request
from pathlib import Path


USER_AGENT = "CapCut-Android/20.0.0"
FILE_URL = re.compile(r"file_url=UrlModel\(url_list=\[([^\]]*)\]", re.S)
ICON_URL = re.compile(r"icon_url=UrlModel\(url_list=\[([^\]]*)\]", re.S)
ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "asset-vault/runtime/text-templates-runtime.json"
REPO = Path(
    "/Users/votaminh99/Documents/Android/msc_iaa/011/msc011_file")
THUMBS = REPO / "previews/text-templates/thumbs"
OUTPUT = REPO / "text-templates-preview.json"
RAW_ROOT = (
    "https://raw.githubusercontent.com/votaminh/msc011_file/main/"
    "previews/text-templates/thumbs/"
)


def first_url(pattern, raw):
    match = pattern.search(raw or "")
    if not match:
        return ""
    value = match.group(1).split(",", 1)[0].strip()
    return value if value.startswith(("http://", "https://")) else ""


def download(url, path):
    if path.is_file() and path.stat().st_size > 0:
        return path.stat().st_size
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        if response.getcode() != 200:
            raise RuntimeError(f"HTTP {response.getcode()}")
        data = response.read()
    if not data:
        raise ValueError("empty preview")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)
    return len(data)


def main():
    runtime = json.loads(RUNTIME.read_text(encoding="utf-8"))
    items = []
    urls = {}
    for row in runtime.get("templates", []):
        effect = row.get("effect") or {}
        effect_id = str(effect.get("effectId") or "")
        raw = effect.get("raw") or ""
        if not effect_id or not first_url(FILE_URL, raw):
            continue
        icon = first_url(ICON_URL, raw)
        if not icon:
            continue
        extra = json.loads(effect.get("extra") or "{}")
        sdk = json.loads(effect.get("sdkExtra") or "{}")
        urls[effect_id] = icon
        items.append({
            "effectId": effect_id,
            "resourceId": effect.get("resourceId") or effect_id,
            "name": effect.get("name") or effect_id,
            "categoryId": (row.get("category") or {}).get("id") or "",
            "categoryName": (row.get("category") or {}).get("name") or "",
            "previewTimeMs": int(extra.get("static_preview_time") or 0),
            "vip": bool(extra.get("is_vip")),
            "dependencies": sdk.get("depend_resource_list") or [],
            "thumb": RAW_ROOT + effect_id + ".webp",
        })

    failures = []

    def fetch(effect_id, url):
        try:
            size = download(url, THUMBS / f"{effect_id}.webp")
            return effect_id, size, None
        except Exception as error:
            return effect_id, 0, f"{type(error).__name__}: {error}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        futures = [
            pool.submit(fetch, effect_id, url)
            for effect_id, url in urls.items()
        ]
        for index, future in enumerate(
                concurrent.futures.as_completed(futures), 1):
            effect_id, size, error = future.result()
            if error:
                failures.append({"effectId": effect_id, "error": error})
            if index % 100 == 0 or index == len(futures):
                print(
                    f"{index}/{len(futures)} failures={len(failures)}",
                    flush=True,
                )

    failures_by_id = {item["effectId"] for item in failures}
    published = [item for item in items
                 if item["effectId"] not in failures_by_id]
    payload = {
        "version": 1,
        "source": "CapCut 20.0.0 runtime",
        "count": len(published),
        "uniqueEffects": len(urls) - len(failures),
        "failures": failures,
        "items": published,
    }
    data = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(data, encoding="utf-8")
    temporary.replace(OUTPUT)
    print(
        f"published={len(published)} unique={payload['uniqueEffects']}"
        f" output={OUTPUT}"
    )


if __name__ == "__main__":
    main()
