#!/usr/bin/env python3
"""Split and upload CapCut effect-model ZIPs through Telegram."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from text_animation_assets import atomic_json, load_json, send_document


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "asset-vault/models/effectmodel/effectmodel-full-20261105.zip"
INVENTORY = ROOT / "asset-vault/models/effectmodel/effectmodel-inventory.json"
MODEL_MANIFEST = ROOT / "asset-vault/models/effectmodel/manifest.json"
DEMO = ROOT / "demo-upload/effect-models"
PARTS = DEMO / "parts"
MANIFEST = DEMO / "manifest.json"
PART_BYTES = 15_000_000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare():
    if not SOURCE.is_file():
        raise SystemExit(f"Missing model ZIP: {SOURCE}")
    PARTS.mkdir(parents=True, exist_ok=True)
    previous = load_json(MANIFEST, {"parts": []})
    previous_parts = {
        part["name"]: part for part in previous.get("parts", [])
    }
    parts = []
    with SOURCE.open("rb") as source:
        index = 1
        while True:
            data = source.read(PART_BYTES)
            if not data:
                break
            name = f"{SOURCE.stem}.part{index:03d}"
            target = PARTS / name
            if not target.is_file() or target.stat().st_size != len(data):
                target.write_bytes(data)
            prior = previous_parts.get(name, {})
            part_sha = sha256(target)
            if (
                int(prior.get("bytes") or -1) != len(data)
                or prior.get("sha256") != part_sha
            ):
                prior = {}
            parts.append({
                "name": name,
                "bytes": len(data),
                "sha256": part_sha,
                "file_id": prior.get("file_id") or "",
                "file_unique_id": prior.get("file_unique_id") or "",
                "message_id": prior.get("message_id"),
                "chat_id": prior.get("chat_id") or "",
                "telegram_file_name": prior.get("telegram_file_name") or name,
            })
            index += 1
    keep = {part["name"] for part in parts}
    for stale in PARTS.glob(f"{SOURCE.stem}.part*"):
        if stale.name not in keep:
            stale.unlink()
    model_manifest = load_json(MODEL_MANIFEST, {})
    atomic_json(MANIFEST, {
        "version": 1,
        "kind": "effect-model-demo",
        "source": str(SOURCE),
        "zip": {
            "bytes": SOURCE.stat().st_size,
            "sha256": sha256(SOURCE),
        },
        "inventory": {
            "bytes": INVENTORY.stat().st_size,
            "sha256": sha256(INVENTORY),
        },
        "modelManifest": {
            "fileCount": model_manifest.get("fileCount"),
            "totalBytes": model_manifest.get("totalBytes"),
        },
        "parts": parts,
    })
    print(
        f"PASS parts={len(parts)} bytes={sum(p['bytes'] for p in parts)} "
        f"manifest={MANIFEST}"
    )


def upload(chat_id: str | None):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = str(chat_id or os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
    manifest = load_json(MANIFEST, None)
    if not isinstance(manifest, dict):
        raise SystemExit(f"Missing manifest: {MANIFEST}")
    for index, part in enumerate(manifest["parts"], 1):
        if part.get("file_id"):
            print(
                f"[{index}/{len(manifest['parts'])}] skip "
                f"{part['name']} {part['file_id']}",
                flush=True,
            )
            continue
        path = PARTS / part["name"]
        result = send_document(
            token, chat, path,
            f"CapCut effectmodel {index}/{len(manifest['parts'])} | {path.name}")
        document = result.get("document") or {}
        part.update({
            "file_id": document.get("file_id") or "",
            "file_unique_id": document.get("file_unique_id") or "",
            "message_id": result.get("message_id"),
            "chat_id": chat,
            "telegram_file_name": document.get("file_name") or path.name,
        })
        if not part["file_id"]:
            raise SystemExit(f"No Telegram file_id for {path.name}")
        atomic_json(MANIFEST, manifest)
        print(
            f"[{index}/{len(manifest['parts'])}] uploaded "
            f"{part['name']} {part['file_id']}",
            flush=True,
        )


def export_app(output: Path):
    manifest = load_json(MANIFEST, None)
    if not isinstance(manifest, dict):
        raise SystemExit(f"Missing manifest: {MANIFEST}")
    parts = []
    for part in manifest.get("parts", []):
        if not part.get("file_id"):
            raise SystemExit(f"Missing file_id for {part.get('name')}")
        parts.append({
            key: part.get(key)
            for key in (
                "name", "bytes", "sha256", "file_id", "file_unique_id"
            )
        })
    atomic_json(output, {
        "version": 1,
        "kind": "effect-model-demo",
        "zipBytes": manifest["zip"]["bytes"],
        "zipSha256": manifest["zip"]["sha256"],
        "fileCount": manifest["modelManifest"]["fileCount"],
        "modelBytes": manifest["modelManifest"]["totalBytes"],
        "parts": parts,
    })
    print(f"PASS app_manifest={output} parts={len(parts)}")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prep = subparsers.add_parser("prepare")
    prep.set_defaults(func=lambda _args: prepare())
    upload_parser = subparsers.add_parser("upload")
    upload_parser.add_argument("--chat-id")
    upload_parser.set_defaults(func=lambda args: upload(args.chat_id))
    export = subparsers.add_parser("export-app")
    export.add_argument("--output", type=Path, required=True)
    export.set_defaults(func=lambda args: export_app(args.output))
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
