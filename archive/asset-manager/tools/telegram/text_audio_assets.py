#!/usr/bin/env python3
"""Manage CapCut Text-to-speech catalog/assets through Telegram.

The exported catalog contains cloud voice identifiers (11labs/bigtts), avatar
images, audition audio and optional frame images. Each unique file is uploaded
as its own Telegram document; no bot token is written to disk.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from text_animation_assets import (  # noqa: E402
    api_request,
    atomic_json,
    load_json,
    send_document,
)


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "asset-vault/text-audio"
RUNTIME = BASE / "runtime"
ASSETS = BASE / "assets"
CATALOG = BASE / "catalog.json"
MANIFEST = BASE / "manifest.json"
INDEX = ROOT / "tools/telegram/text-audio-telegram-index.json"

URL_ROLES = {
    "tone_avatar_url": ("avatar", "png"),
    "test_audio": ("audition", "mp3"),
    "light_icon_frame": ("frame-light", "png"),
    "dark_icon_frame": ("frame-dark", "png"),
    "transparent_icon_frame": ("frame-transparent", "png"),
    "avatar_ex": ("catalog-avatar", "png"),
}

PREVIEW_DIRS = {
    "avatar": "avatars",
    "catalog-avatar": "catalog-avatars",
    "frame-light": "frames/light",
    "frame-dark": "frames/dark",
    "frame-transparent": "frames/transparent",
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_json(value: str, fallback):
    try:
        parsed = json.loads(value or "")
        return parsed
    except (TypeError, ValueError):
        return fallback


def safe_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-")
    return value[:60] or "asset"


def normalize_extension(content_type: str, role: str, default: str) -> str:
    mime = content_type.split(";", 1)[0].strip().lower()
    known = {
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "audio/aac": ".aac",
        "audio/wav": ".wav",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "application/json": ".json",
    }
    if mime in known:
        return known[mime]
    if role in ("avatar", "catalog-avatar", "frame-light", "frame-dark",
                "frame-transparent"):
        return "." + default
    return "." + default


def download(url: str, target: Path) -> tuple[str, str]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "CapCut/20.0.0 Android"},
    )
    last_error = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read()
                content_type = response.headers.get("Content-Type", "")
            if not data:
                raise RuntimeError("empty response")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            return content_type, sha256_bytes(data)
        except (OSError, RuntimeError, urllib.error.URLError) as error:
            last_error = error
            time.sleep(1 + attempt)
    raise RuntimeError(f"download failed: {url}: {last_error}")


def command_build(args):
    raw = load_json(args.input, None)
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise SystemExit(f"Invalid runtime catalog: {args.input}")

    voices = []
    seen_voices = set()
    unique_urls: dict[str, dict] = {}
    for item in raw["items"]:
        name = str(item.get("name") or "").strip()
        effect_id = str(item.get("effect_id") or "").strip()
        if not name or not effect_id or effect_id in seen_voices:
            continue
        seen_voices.add(effect_id)
        extra = parse_json(item.get("extra") or "", {})
        tonetype = parse_json(extra.get("tonetype") or "", {})
        mock = parse_json(extra.get("mock_tone_info") or "", {})
        voice = {
            "voiceId": effect_id,
            "resourceId": str(item.get("resource_id") or effect_id),
            "packageId": str(item.get("id") or ""),
            "name": name,
            "panel": str(item.get("panel") or ""),
            "platform": str(tonetype.get("platform") or ""),
            "voiceType": str(tonetype.get("voice_type") or ""),
            "rate": str(tonetype.get("rate") or ""),
            "version": str(tonetype.get("version") or ""),
            "mockSpeakerId": str(mock.get("mock_speaker_id") or ""),
            "vip": bool(extra.get("is_vip")),
            "business": bool(extra.get("is_business")),
            "gender": str(extra.get("voice_gender") or ""),
            "readingSpeed": extra.get("reading_speed"),
            "rawExtra": extra,
            "assets": {},
        }
        for key, (role, default_extension) in URL_ROLES.items():
            url = extra.get(key)
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                continue
            url_hash = sha256_bytes(url.encode())[:16]
            asset_key = f"{role}:{url_hash}"
            entry = unique_urls.setdefault(asset_key, {
                "key": asset_key,
                "role": role,
                "url": url,
                "defaultExtension": default_extension,
                "voiceIds": [],
                "voiceNames": [],
            })
            if effect_id not in entry["voiceIds"]:
                entry["voiceIds"].append(effect_id)
                entry["voiceNames"].append(name)
            voice["assets"][role] = asset_key
        voices.append(voice)

    records = []
    for position, entry in enumerate(sorted(unique_urls.values(),
                                            key=lambda value: value["key"]), 1):
        provisional = ASSETS / entry["role"] / (
            safe_name(entry["voiceIds"][0]) + "-" + entry["key"].split(":")[1]
            + "." + entry["defaultExtension"])
        content_type, _ = download(entry["url"], provisional)
        extension = normalize_extension(
            content_type, entry["role"], entry["defaultExtension"])
        target = provisional.with_suffix(extension)
        if target != provisional:
            provisional.replace(target)
        records.append({
            **entry,
            "path": str(target.relative_to(BASE)),
            "bytes": target.stat().st_size,
            "sha256": sha256_file(target),
            "contentType": content_type,
        })
        print(
            f"[{position}/{len(unique_urls)}] {entry['role']} "
            f"{target.name} {target.stat().st_size}B",
            flush=True,
        )

    by_key = {record["key"]: {
        "path": record["path"],
        "bytes": record["bytes"],
        "sha256": record["sha256"],
        "contentType": record["contentType"],
        "sourceUrl": record["url"],
    } for record in records}
    for voice in voices:
        for role, key in list(voice["assets"].items()):
            voice["assets"][role] = by_key[key]

    RUNTIME.mkdir(parents=True, exist_ok=True)
    runtime_copy = RUNTIME / "tts_catalog_effects.json"
    shutil.copyfile(args.input, runtime_copy)
    catalog = {
        "version": 1,
        "kind": "capcut-text-to-speech",
        "source": "CapCut 20 ToneSelectViewModel / ToneTypeSelectNewAdapter",
        "voiceCount": len(voices),
        "voices": voices,
    }
    atomic_json(CATALOG, catalog)
    manifest = {
        "version": 1,
        "kind": "text-audio-assets",
        "runtimeCatalog": str(runtime_copy.relative_to(BASE)),
        "catalog": str(CATALOG.relative_to(BASE)),
        "voiceCount": len(voices),
        "assetCount": len(records),
        "assets": records,
    }
    atomic_json(MANIFEST, manifest)
    print(
        f"PASS voices={len(voices)} assets={len(records)} "
        f"catalog={CATALOG}",
        flush=True,
    )


def verify_manifest():
    manifest = load_json(MANIFEST, None)
    catalog = load_json(CATALOG, None)
    if not isinstance(manifest, dict) or not isinstance(catalog, dict):
        raise SystemExit("Run build first")
    failures = []
    for item in manifest.get("assets", []):
        path = BASE / item["path"]
        if not path.is_file():
            failures.append({"path": item["path"], "error": "missing"})
            continue
        if path.stat().st_size != int(item["bytes"]):
            failures.append({"path": item["path"], "error": "size"})
        if sha256_file(path) != item["sha256"]:
            failures.append({"path": item["path"], "error": "sha256"})
    print(
        f"voices={len(catalog.get('voices', []))} "
        f"assets={len(manifest.get('assets', []))} failures={len(failures)}"
    )
    for failure in failures[:50]:
        print("FAIL", failure)
    return 1 if failures else 0


def upload_files(args):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = str(args.chat_id or os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        raise SystemExit("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")

    manifest = load_json(MANIFEST, None)
    catalog = load_json(CATALOG, None)
    if not isinstance(manifest, dict) or not isinstance(catalog, dict):
        raise SystemExit("Run build first")

    previous = load_json(INDEX, {"version": 1, "items": []})
    uploaded = {
        item["sha256"]: item
        for item in previous.get("items", [])
        if item.get("file_id")
    }
    index = {
        "version": 1,
        "chat_id": chat_id,
        "catalog": str(CATALOG.relative_to(ROOT)),
        "items": [],
    }
    files = list(manifest["assets"])
    files.extend([
        {
            "key": "catalog",
            "role": "catalog",
            "path": str(CATALOG.relative_to(BASE)),
            "sha256": sha256_file(CATALOG),
            "bytes": CATALOG.stat().st_size,
            "voiceIds": [],
            "voiceNames": [],
        },
        {
            "key": "runtime-catalog",
            "role": "runtime-catalog",
            "path": manifest["runtimeCatalog"],
            "sha256": sha256_file(BASE / manifest["runtimeCatalog"]),
            "bytes": (BASE / manifest["runtimeCatalog"]).stat().st_size,
            "voiceIds": [],
            "voiceNames": [],
        },
    ])

    for position, item in enumerate(files, 1):
        key = item.get("key") or item["path"]
        digest = item["sha256"]
        existing = uploaded.get(digest)
        if existing and existing.get("bytes") == item["bytes"]:
            index["items"].append(existing)
            print(f"[{position}/{len(files)}] skip {key}", flush=True)
            continue
        path = BASE / item["path"]
        names = ", ".join(item.get("voiceNames", [])[:2])
        caption = f"Text+Audio | {item['role']} | {key} | {names}"
        while True:
            try:
                message = send_document(token, chat_id, path, caption)
                break
            except RuntimeError as error:
                text = str(error)
                if "retry after" not in text.lower():
                    raise
                delay = 10
                match = re.search(r"retry after (\\d+)", text, re.IGNORECASE)
                if match:
                    delay = int(match.group(1))
                print(f"rate limited; sleeping {delay}s", flush=True)
                time.sleep(delay)
        document = message.get("document") or {}
        record = {
            "key": key,
            "role": item["role"],
            "path": item["path"],
            "bytes": item["bytes"],
            "sha256": digest,
            "voiceIds": item.get("voiceIds", []),
            "voiceNames": item.get("voiceNames", []),
            "file_id": document.get("file_id"),
            "file_unique_id": document.get("file_unique_id"),
            "message_id": message.get("message_id"),
            "telegram_file_name": document.get("file_name"),
        }
        index["items"].append(record)
        atomic_json(INDEX, index)
        print(
            f"[{position}/{len(files)}] upload {key} "
            f"{item['bytes']}B -> {record['file_id']}",
            flush=True,
        )
        time.sleep(args.delay)


def command_download(args):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")
    index = load_json(INDEX, None)
    if not isinstance(index, dict):
        raise SystemExit(f"Missing index: {INDEX}")
    matches = [
        item for item in index.get("items", [])
        if item.get("key") == args.key
    ]
    if not matches:
        raise SystemExit(f"Unknown key: {args.key}")
    item = matches[0]
    info = api_request(token, "getFile", {"file_id": item["file_id"]})
    file_path = info.get("file_path") or ""
    if not file_path:
        raise SystemExit("Telegram getFile returned no path")
    url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read()
    if sha256_bytes(data) != item["sha256"]:
        raise SystemExit("Downloaded file hash mismatch")
    args.output.write_bytes(data)
    print(f"PASS {args.key} -> {args.output}")


def command_index_user_uploads(args):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = str(args.chat_id or os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        raise SystemExit("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")

    messages = load_json(args.messages, {})
    manifest = load_json(MANIFEST, None)
    if not isinstance(messages, dict) or not isinstance(manifest, dict):
        raise SystemExit("Run build and provide the Bot API message dump")

    recent = [
        item for item in messages.get("files", [])
        if int(item.get("date") or 0) >= args.since
        and item.get("message_id")
    ]
    expected_by_name = {}
    for record in manifest.get("assets", []):
        expected_by_name[Path(record["path"]).name] = {
            **record,
            "telegram_path": record["path"],
        }
    expected_by_name["catalog.json"] = {
        "key": "catalog",
        "role": "catalog",
        "path": str(CATALOG.relative_to(BASE)),
        "telegram_path": str(CATALOG.relative_to(BASE)),
        "sha256": sha256_file(CATALOG),
        "bytes": CATALOG.stat().st_size,
        "voiceIds": [],
        "voiceNames": [],
    }
    expected_by_name["manifest.json"] = {
        "key": "manifest",
        "role": "manifest",
        "path": str(MANIFEST.relative_to(BASE)),
        "telegram_path": str(MANIFEST.relative_to(BASE)),
        "sha256": sha256_file(MANIFEST),
        "bytes": MANIFEST.stat().st_size,
        "voiceIds": [],
        "voiceNames": [],
    }
    runtime_name = Path(manifest["runtimeCatalog"]).name
    runtime_path = BASE / manifest["runtimeCatalog"]
    expected_by_name[runtime_name] = {
        "key": "runtime-catalog",
        "role": "runtime-catalog",
        "path": manifest["runtimeCatalog"],
        "telegram_path": manifest["runtimeCatalog"],
        "sha256": sha256_file(runtime_path),
        "bytes": runtime_path.stat().st_size,
        "voiceIds": [],
        "voiceNames": [],
    }

    api_root = "https://api.telegram.org/bot" + token + "/"

    def api(method, payload):
        data = urllib.parse.urlencode(payload).encode()
        request = urllib.request.Request(api_root + method, data=data)
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.load(response)
        if not result.get("ok"):
            raise RuntimeError(f"{method}: {result}")
        return result["result"]

    previous = load_json(INDEX, {"items": []})
    indexed = [
        item for item in previous.get("items", [])
        if item.get("file_id") and item.get("source_message_id")
    ]
    indexed_by_message = {
        int(item["source_message_id"]): item for item in indexed
    }
    failures = []
    for position, message in enumerate(recent, 1):
        name = str(message.get("name") or "")
        expected = expected_by_name.get(name)
        if expected is None:
            failures.append({"message_id": message["message_id"], "name": name,
                             "error": "not in manifest"})
            continue
        existing = indexed_by_message.get(int(message["message_id"]))
        if existing:
            print(f"[{position}/{len(recent)}] skip indexed {name}",
                  flush=True)
            continue
        forwarded = api("forwardMessage", {
            "chat_id": chat_id,
            "from_chat_id": chat_id,
            "message_id": str(message["message_id"]),
            "disable_notification": "true",
        })
        copy_id = forwarded["message_id"]
        try:
            media = (
                forwarded.get("document")
                or forwarded.get("audio")
                or forwarded.get("video")
                or forwarded.get("animation")
                or forwarded.get("sticker")
                or {}
            )
            file_id = media.get("file_id")
            if not file_id:
                raise RuntimeError("forwarded message has no file_id")
            record = {
                "key": expected["key"],
                "role": expected["role"],
                "path": expected["telegram_path"],
                "bytes": expected["bytes"],
                "sha256": expected["sha256"],
                "voiceIds": expected.get("voiceIds", []),
                "voiceNames": expected.get("voiceNames", []),
                "source_message_id": message["message_id"],
                "file_id": file_id,
                "file_unique_id": media.get("file_unique_id"),
                "telegram_file_name": media.get("file_name") or name,
            }
            indexed.append(record)
            indexed_by_message[int(message["message_id"])] = record
            atomic_json(INDEX, {
                "version": 1,
                "source": "Telegram user uploads",
                "chat_id": chat_id,
                "items": indexed,
            })
        except Exception as error:
            failures.append({"message_id": message["message_id"], "name": name,
                             "error": str(error)})
        finally:
            try:
                api("deleteMessage", {
                    "chat_id": chat_id,
                    "message_id": str(copy_id),
                })
            except Exception as error:
                print(f"delete failed message={copy_id}: {error}", flush=True)
        print(f"[{position}/{len(recent)}] index {name} "
              f"file_id={indexed[-1]['file_id'] if indexed else 'FAIL'}",
              flush=True)
        time.sleep(args.delay)

    if args.sticker_message_id:
        forwarded = api("forwardMessage", {
            "chat_id": chat_id,
            "from_chat_id": chat_id,
            "message_id": str(args.sticker_message_id),
            "disable_notification": "true",
        })
        copy_id = forwarded["message_id"]
        try:
            sticker = forwarded.get("sticker") or {}
            size = int(sticker.get("file_size") or 0)
            candidates = [
                record for record in expected_by_name.values()
                if record["role"] == "catalog-avatar"
                and int(record["bytes"]) == size
            ]
            if len(candidates) != 1 or not sticker.get("file_id"):
                raise RuntimeError(
                    f"cannot map sticker size={size} candidates={len(candidates)}")
            expected = candidates[0]
            record = next(
                (item for item in indexed if item["key"] == expected["key"]),
                None,
            )
            if record is None:
                record = {
                    "key": expected["key"],
                    "role": expected["role"],
                    "path": expected["telegram_path"],
                    "bytes": expected["bytes"],
                    "sha256": expected["sha256"],
                    "voiceIds": expected.get("voiceIds", []),
                    "voiceNames": expected.get("voiceNames", []),
                }
                indexed.append(record)
            record["sticker_message_id"] = args.sticker_message_id
            record["file_id"] = sticker["file_id"]
            record["file_unique_id"] = sticker.get("file_unique_id")
            record["telegram_file_name"] = Path(record["path"]).name
            record["converted_to_sticker"] = True
        finally:
            api("deleteMessage", {
                "chat_id": chat_id,
                "message_id": str(copy_id),
            })

    missing = sorted(set(expected_by_name) - {
        Path(item["path"]).name for item in indexed
    })
    atomic_json(INDEX, {
        "version": 1,
        "source": "Telegram user uploads",
        "chat_id": chat_id,
        "items": indexed,
    })
    print(
        f"PASS indexed={len(indexed)} failures={len(failures)} "
        f"missing={len(missing)} index={INDEX}",
        flush=True,
    )
    if failures or missing:
        print(json.dumps({"failures": failures, "missing": missing},
                         ensure_ascii=False, indent=2))
        return 1
    return 0


def command_export_app_catalog(args):
    catalog = load_json(CATALOG, None)
    index = load_json(INDEX, None)
    if not isinstance(catalog, dict) or not isinstance(index, dict):
        raise SystemExit("Run build and index-user-uploads first")
    files = {item["key"]: item for item in index.get("items", [])}
    files_by_path = {item["path"]: item for item in index.get("items", [])}
    voices = []
    for voice in catalog.get("voices", []):
        assets = {}
        for role, asset in voice.get("assets", {}).items():
            record = files_by_path.get(asset.get("path"))
            if not record or not record.get("file_id"):
                continue
            assets[role] = {
                "path": record["path"],
                "bytes": record["bytes"],
                "sha256": record["sha256"],
                "telegramFileId": record["file_id"],
                "sticker": bool(record.get("converted_to_sticker")),
            }
            if role in PREVIEW_DIRS and args.preview_base:
                assets[role]["previewUrl"] = (
                    args.preview_base.rstrip("/") + "/"
                    + PREVIEW_DIRS[role] + "/"
                    + voice["voiceId"] + ".webp"
                )
        voices.append({
            "voiceId": voice["voiceId"],
            "resourceId": voice["resourceId"],
            "packageId": voice["packageId"],
            "name": voice["name"],
            "platform": voice["platform"],
            "voiceType": voice["voiceType"],
            "rate": voice["rate"],
            "version": voice["version"],
            "mockSpeakerId": voice["mockSpeakerId"],
            "vip": voice["vip"],
            "business": voice["business"],
            "gender": voice["gender"],
            "readingSpeed": voice["readingSpeed"],
            "assets": assets,
        })
    payload = {
        "version": 1,
        "kind": "capcut-text-to-speech",
        "voiceCount": len(voices),
        "voices": voices,
        "runtimeCatalog": files.get("runtime-catalog", {}).get("file_id", ""),
        "catalog": files.get("catalog", {}).get("file_id", ""),
        "manifest": files.get("manifest", {}).get("file_id", ""),
    }
    atomic_json(args.output, payload)
    print(f"PASS voices={len(voices)} output={args.output}")


def command_export_previews(args):
    catalog = load_json(CATALOG, None)
    if not isinstance(catalog, dict):
        raise SystemExit("Run build first")
    items = []
    for voice in catalog.get("voices", []):
        for role, directory in PREVIEW_DIRS.items():
            asset = voice.get("assets", {}).get(role)
            if not asset:
                continue
            source = BASE / asset["path"]
            if not source.is_file():
                continue
            voice_id = voice["voiceId"]
            target = args.repo / "previews/text-to-speech" / directory
            target.mkdir(parents=True, exist_ok=True)
            output = target / (safe_name(voice_id) + ".webp")
            with Image.open(source) as image:
                image = image.convert("RGBA")
                image.thumbnail((160, 160), Image.Resampling.LANCZOS)
                image.save(output, "WEBP", quality=82, method=6)
            items.append({
                "voiceId": voice_id,
                "role": role,
                "name": voice["name"],
                "platform": voice["platform"],
                "voiceType": voice["voiceType"],
                "vip": voice["vip"],
                "path": str(output.relative_to(args.repo)),
                "bytes": output.stat().st_size,
                "sha256": sha256_file(output),
            })
            print(f"[{len(items)}] {role} {voice['name']} "
                  f"{output.stat().st_size}B", flush=True)
    payload = {
        "schemaVersion": 1,
        "source": "CapCut 20 Text-to-Speech avatar runtime",
        "count": len(items),
        "items": items,
    }
    atomic_json(args.repo / "text-to-speech-preview.json", payload)
    total = sum(item["bytes"] for item in items)
    print(f"PASS previews={len(items)} bytes={total}")


def build_parser():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build")
    build.add_argument("--input", type=Path, required=True)
    build.set_defaults(func=command_build)

    verify = commands.add_parser("verify")
    verify.set_defaults(func=lambda _args: verify_manifest())

    upload = commands.add_parser("upload")
    upload.add_argument("--chat-id", default=os.environ.get("TELEGRAM_CHAT_ID"))
    upload.add_argument("--delay", type=float, default=1.2)
    upload.set_defaults(func=upload_files)

    download = commands.add_parser("download")
    download.add_argument("--key", required=True)
    download.add_argument("--output", type=Path, required=True)
    download.set_defaults(func=command_download)

    index_user = commands.add_parser("index-user-uploads")
    index_user.add_argument("--messages", type=Path, required=True)
    index_user.add_argument("--chat-id", default=os.environ.get("TELEGRAM_CHAT_ID"))
    index_user.add_argument("--since", type=int, required=True)
    index_user.add_argument("--sticker-message-id", type=int)
    index_user.add_argument("--delay", type=float, default=0.2)
    index_user.set_defaults(func=command_index_user_uploads)

    export_app = commands.add_parser("export-app-catalog")
    export_app.add_argument("--output", type=Path, required=True)
    export_app.add_argument("--preview-base")
    export_app.set_defaults(func=command_export_app_catalog)

    export_previews = commands.add_parser("export-previews")
    export_previews.add_argument("--repo", type=Path, required=True)
    export_previews.set_defaults(func=command_export_previews)
    return parser


def main():
    args = build_parser().parse_args()
    result = args.func(args)
    raise SystemExit(result or 0)


if __name__ == "__main__":
    main()
