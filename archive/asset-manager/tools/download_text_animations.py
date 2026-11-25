#!/usr/bin/env python3
"""Download the captured CapCut text-animation bundles into app assets."""

from __future__ import annotations

import concurrent.futures
import json
import pathlib
import sys
import urllib.request
import zipfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "verification/text-animation-dump/capcut-text-animations-all.json"
OUTPUT = ROOT / "app/src/main/assets/text_animations"
WORKERS = 12
USER_AGENT = "CapCut-Android/20.0.0"


def valid_zip(path: pathlib.Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            return bool(archive.namelist())
    except (OSError, zipfile.BadZipFile):
        return False


def download(item: dict) -> tuple[dict | None, dict | None]:
    effect_id = item.get("effectId")
    urls = (item.get("fileUrl") or {}).get("urls") or []
    if not effect_id or not urls:
        return None, {"effectId": effect_id, "name": item.get("name"),
                      "error": "missing effectId or URL"}

    destination = OUTPUT / f"{effect_id}.zip"
    if valid_zip(destination):
        return {
            "category": item.get("category"),
            "name": item.get("name"),
            "effectId": effect_id,
            "resourceId": item.get("resourceId"),
            "asset": f"text_animations/{destination.name}",
        }, None

    last_error = None
    for url in urls:
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = response.read()
            if not payload.startswith(b"PK"):
                raise ValueError("response is not a zip")
            temporary = destination.with_suffix(".zip.part")
            temporary.write_bytes(payload)
            if not valid_zip(temporary):
                temporary.unlink(missing_ok=True)
                raise ValueError("downloaded zip is invalid")
            temporary.replace(destination)
            return {
                "category": item.get("category"),
                "name": item.get("name"),
                "effectId": effect_id,
                "resourceId": item.get("resourceId"),
                "asset": f"text_animations/{destination.name}",
            }, None
        except Exception as error:  # noqa: BLE001 - report every failed CDN item
            last_error = f"{type(error).__name__}: {error}"

    return None, {
        "effectId": effect_id,
        "name": item.get("name"),
        "error": last_error,
    }


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    items = [
        item
        for group in source["categories"].values()
        for item in group["items"]
    ]
    downloaded = []
    failures = []
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=WORKERS) as executor:
        futures = [executor.submit(download, item) for item in items]
        for index, future in enumerate(
                concurrent.futures.as_completed(futures), 1):
            result, failure = future.result()
            if result is not None:
                downloaded.append(result)
            if failure is not None:
                failures.append(failure)
            if index % 25 == 0 or index == len(futures):
                print(
                    f"{index}/{len(futures)} downloaded={len(downloaded)} "
                    f"failed={len(failures)}",
                    flush=True,
                )

    downloaded.sort(key=lambda item: (
        {"In": 0, "Out": 1, "Loop": 2}.get(item["category"], 9),
        item["name"] or "",
    ))
    catalog = {
        "version": 1,
        "items": downloaded,
        "failures": failures,
    }
    (OUTPUT / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    size = sum(path.stat().st_size for path in OUTPUT.glob("*.zip"))
    print(
        f"catalog={len(downloaded)} failures={len(failures)} "
        f"bytes={size} output={OUTPUT}"
    )
    return 0 if downloaded else 1


if __name__ == "__main__":
    raise SystemExit(main())
