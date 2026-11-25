#!/usr/bin/env python3
"""Generate 100 non-runnable text-animation concept proposals.

The proposals are intentionally separate from the canonical manifest. They do
not invent CapCut effectId/resourceId values and cannot be imported until a
compatible effect package is captured or produced.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
CATEGORY_ORDER = {"In": 0, "Out": 1, "Loop": 2}

BASE = {
    "Aurora Curtain": {
        "visual": "Các dải aurora mềm chạy dọc phía sau từng ký tự.",
        "tags": ["luminous", "gradient", "ribbon"],
        "complexity": "medium",
    },
    "Origami Bloom": {
        "visual": "Ký tự mở ra như các mảnh giấy gấp, tạo cảm giác bloom hình học.",
        "tags": ["paper", "geometric", "bloom"],
        "complexity": "medium",
    },
    "Liquid Chrome": {
        "visual": "Bề mặt chữ biến dạng như chrome lỏng với phản xạ kim loại.",
        "tags": ["metal", "liquid", "shader"],
        "complexity": "high",
    },
    "Neon Circuit": {
        "visual": "Các đường mạch neon vẽ và lan truyền qua thân ký tự.",
        "tags": ["neon", "circuit", "glow"],
        "complexity": "medium",
    },
    "Paper Lantern": {
        "visual": "Ký tự lơ lửng như đèn lồng giấy với ánh sáng ấm.",
        "tags": ["lantern", "warm", "float"],
        "complexity": "low",
    },
    "Starlight Ribbon": {
        "visual": "Một dải sao uốn quanh chữ và để lại trail lấp lánh.",
        "tags": ["stars", "ribbon", "particle"],
        "complexity": "medium",
    },
    "Glass Prism": {
        "visual": "Chữ tách màu qua lăng kính thủy tinh với highlight khúc xạ.",
        "tags": ["glass", "prism", "chromatic"],
        "complexity": "high",
    },
    "Ember Drift": {
        "visual": "Tàn lửa nhỏ bốc lên và tan dần quanh đường viền chữ.",
        "tags": ["ember", "fire", "particle"],
        "complexity": "medium",
    },
    "Water Ripple": {
        "visual": "Ký tự nổi trên mặt nước với gợn sóng lan theo từng nét.",
        "tags": ["water", "ripple", "distortion"],
        "complexity": "high",
    },
    "Chromatic Split": {
        "visual": "Các kênh RGB tách và hội tụ nhanh tạo nhịp digital.",
        "tags": ["chromatic", "digital", "glitch"],
        "complexity": "low",
    },
    "Frost Crystal": {
        "visual": "Tinh thể băng mọc từ mép ký tự rồi phủ lớp sương lấp lánh.",
        "tags": ["ice", "crystal", "sparkle"],
        "complexity": "medium",
    },
    "Retro TV": {
        "visual": "Chữ đi qua scanline CRT, nhiễu màu và tín hiệu analog.",
        "tags": ["retro", "crt", "analog"],
        "complexity": "medium",
    },
    "Comic Pop": {
        "visual": "Chữ bật ra cùng burst comic và rung nhẹ như bong bóng thoại.",
        "tags": ["comic", "burst", "bold"],
        "complexity": "low",
    },
    "Ink Brush": {
        "visual": "Nét mực loang dần để lộ ký tự với texture giấy.",
        "tags": ["ink", "brush", "paper"],
        "complexity": "medium",
    },
    "Light Pencil": {
        "visual": "Một cây bút sáng vẽ từng nét chữ trên nền tối.",
        "tags": ["light", "draw", "neon"],
        "complexity": "low",
    },
    "Laser Etch": {
        "visual": "Tia laser khắc từng nét chữ và để lại viền nóng rực.",
        "tags": ["laser", "etch", "glow"],
        "complexity": "medium",
    },
    "Hologram Rise": {
        "visual": "Ký tự dựng lên bằng scanline và lớp hologram bán trong suốt.",
        "tags": ["hologram", "scanline", "future"],
        "complexity": "high",
    },
    "Magnetic Snap": {
        "visual": "Các mảnh ký tự bị hút từ ngoài vào tâm rồi khóa lại.",
        "tags": ["magnetic", "snap", "kinetic"],
        "complexity": "low",
    },
    "Balloon Stack": {
        "visual": "Các chữ nâng lên như bóng bay có dây co giãn.",
        "tags": ["balloon", "float", "elastic"],
        "complexity": "low",
    },
    "Petal Scatter": {
        "visual": "Cánh hoa tản quanh chữ với chuyển động xoáy nhẹ.",
        "tags": ["petal", "nature", "particle"],
        "complexity": "medium",
    },
    "Golden Thread": {
        "visual": "Sợi chỉ vàng khâu các ký tự lại thành một cụm chuyển động.",
        "tags": ["gold", "thread", "luxury"],
        "complexity": "medium",
    },
    "Smoke Spiral": {
        "visual": "Khói cuộn xoắn tạo quỹ đạo dẫn mắt qua câu chữ.",
        "tags": ["smoke", "spiral", "soft"],
        "complexity": "medium",
    },
    "Cosmic Dust": {
        "visual": "Bụi sao xoáy thành hình chữ rồi tiếp tục trôi như thiên hà.",
        "tags": ["cosmic", "dust", "orbit"],
        "complexity": "high",
    },
    "Type Stack": {
        "visual": "Nhiều lớp chữ xếp chồng và trượt vào đúng vị trí.",
        "tags": ["type", "layer", "stack"],
        "complexity": "low",
    },
    "Camera Flash": {
        "visual": "Một flash máy ảnh làm chữ hiện rõ trong nhịp chụp.",
        "tags": ["camera", "flash", "impact"],
        "complexity": "low",
    },
    "Kinetic Slice": {
        "visual": "Các lát cắt ngang dọc trượt vào để hoàn thiện ký tự.",
        "tags": ["slice", "kinetic", "panel"],
        "complexity": "medium",
    },
    "Bubble Cluster": {
        "visual": "Các bong bóng trong suốt tụ quanh chữ và phản chiếu ánh sáng.",
        "tags": ["bubble", "transparent", "cluster"],
        "complexity": "medium",
    },
    "Wireframe Build": {
        "visual": "Đường wireframe dựng biên và các mặt của ký tự.",
        "tags": ["wireframe", "build", "tech"],
        "complexity": "medium",
    },
    "Paint Splash": {
        "visual": "Các vệt sơn bắn vào rồi đông lại thành hình chữ.",
        "tags": ["paint", "splash", "texture"],
        "complexity": "medium",
    },
    "Firefly Orbit": {
        "visual": "Đom đóm bay theo quỹ đạo quanh câu chữ với nhịp ngẫu nhiên.",
        "tags": ["firefly", "orbit", "particle"],
        "complexity": "medium",
    },
    "Tape Reel": {
        "visual": "Băng phim quay nhanh và dừng đúng frame chứa chữ.",
        "tags": ["tape", "film", "retro"],
        "complexity": "low",
    },
    "Vinyl Spin": {
        "visual": "Đĩa vinyl xoay tạo groove và phản sáng dưới chân chữ.",
        "tags": ["vinyl", "music", "spin"],
        "complexity": "medium",
    },
    "Stamp Press": {
        "visual": "Một con dấu ấn xuống làm chữ nảy và loang mực.",
        "tags": ["stamp", "impact", "ink"],
        "complexity": "low",
    },
    "Glitch Scan": {
        "visual": "Các block dữ liệu quét ngang và tái cấu trúc ký tự.",
        "tags": ["glitch", "datamosh", "scan"],
        "complexity": "medium",
    },
    "Bokeh Bloom": {
        "visual": "Các đốm bokeh mờ nở ra phía sau và làm nổi chữ.",
        "tags": ["bokeh", "blur", "dreamy"],
        "complexity": "medium",
    },
    "Lens Flare": {
        "visual": "Vệt flare ngang quét qua chữ và để lại highlight mảnh.",
        "tags": ["flare", "lens", "light"],
        "complexity": "low",
    },
}

IN_ITEMS = [
    "Aurora Curtain",
    "Origami Bloom",
    "Liquid Chrome",
    "Neon Circuit",
    "Paper Lantern",
    "Starlight Ribbon",
    "Glass Prism",
    "Ember Drift",
    "Water Ripple",
    "Chromatic Split",
    "Frost Crystal",
    "Retro TV",
    "Comic Pop",
    "Ink Brush",
    "Laser Etch",
    "Hologram Rise",
    "Magnetic Snap",
    "Balloon Stack",
    "Petal Scatter",
    "Golden Thread",
    "Smoke Spiral",
    "Cosmic Dust",
    "Type Stack",
    "Camera Flash",
    "Kinetic Slice",
    "Bubble Cluster",
    "Wireframe Build",
    "Paint Splash",
    "Firefly Orbit",
    "Tape Reel",
    "Vinyl Spin",
    "Stamp Press",
    "Glitch Scan",
    "Bokeh Bloom",
    "Lens Flare",
]

OUT_ITEMS = [
    "Aurora Curtain",
    "Origami Bloom",
    "Liquid Chrome",
    "Neon Circuit",
    "Paper Lantern",
    "Starlight Ribbon",
    "Glass Prism",
    "Ember Drift",
    "Water Ripple",
    "Chromatic Split",
    "Frost Crystal",
    "Retro TV",
    "Comic Pop",
    "Ink Brush",
    "Light Pencil",
    "Hologram Rise",
    "Magnetic Snap",
    "Balloon Stack",
    "Petal Scatter",
    "Golden Thread",
    "Smoke Spiral",
    "Cosmic Dust",
    "Type Stack",
    "Camera Flash",
    "Kinetic Slice",
    "Bubble Cluster",
    "Wireframe Build",
    "Paint Splash",
    "Firefly Orbit",
    "Tape Reel",
    "Vinyl Spin",
    "Stamp Press",
    "Glitch Scan",
    "Bokeh Bloom",
    "Lens Flare",
]

LOOP_ITEMS = [
    "Aurora Curtain",
    "Origami Bloom",
    "Liquid Chrome",
    "Neon Circuit",
    "Paper Lantern",
    "Starlight Ribbon",
    "Glass Prism",
    "Ember Drift",
    "Water Ripple",
    "Chromatic Split",
    "Frost Crystal",
    "Retro TV",
    "Comic Pop",
    "Ink Brush",
    "Light Pencil",
    "Hologram Rise",
    "Magnetic Snap",
    "Balloon Stack",
    "Petal Scatter",
    "Golden Thread",
    "Smoke Spiral",
    "Cosmic Dust",
    "Type Stack",
    "Camera Flash",
    "Kinetic Slice",
    "Bubble Cluster",
    "Wireframe Build",
    "Paint Splash",
    "Firefly Orbit",
    "Lens Flare",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPO / "asset-manifests/text-animations.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO / "asset-manifests/text-animation-proposals-100.json",
    )
    return parser.parse_args()


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def name_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def write_atomic(target: Path, payload: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=target.name + ".", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_name, target)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def proposal(
    number: int,
    category: str,
    base_name: str,
) -> dict[str, Any]:
    base = BASE[base_name]
    if category == "Loop":
        name = f"{base_name} Loop"
        duration_ms = None
        loop_period_ms = {
            "low": 1200,
            "medium": 1600,
            "high": 2200,
        }[base["complexity"]]
        easing = "linear"
        direction = "loop"
    else:
        name = f"{base_name} {category}"
        duration_ms = {
            "low": 450,
            "medium": 700,
            "high": 900,
        }[base["complexity"]]
        loop_period_ms = None
        easing = "cubicOut" if category == "In" else "cubicIn"
        direction = "in" if category == "In" else "out"

    complexity = base["complexity"]
    capabilities = {
        "low": ["TextSystem", "Transform2D", "Tween"],
        "medium": ["TextSystem", "Transform2D", "Tween", "AnimatedTexture"],
        "high": [
            "TextSystem",
            "Transform2D",
            "Tween",
            "AnimatedTexture",
            "Shader",
        ],
    }[complexity]
    return {
        "proposalId": f"text-animation-proposal:{number:03d}",
        "status": "concept",
        "name": name,
        "nameKey": name_key(name),
        "category": category,
        "description": base["visual"],
        "tags": base["tags"] + [category.lower()],
        "timing": {
            "durationMs": duration_ms,
            "loopPeriodMs": loop_period_ms,
            "easing": easing,
            "direction": direction,
        },
        "render": {
            "complexity": complexity,
            "capabilities": capabilities,
        },
        "source": {
            "kind": "concept",
            "effectId": None,
            "resourceId": None,
            "requiresCapturedOrAuthoredPackage": True,
        },
        "requiredPackageFiles": [
            "config.json",
            "content.json or studioAnim.lsanim",
            "textAnim.lsproj when the selected runtime requires it",
            "res/* for textures, videos, shaders, or particle assets",
        ],
    }


def main() -> int:
    args = parse_args()
    manifest = read_json(args.manifest)
    existing_items = list(manifest.get("items", {}).values())
    existing = {
        name_key(item.get("name") or "")
        for item in existing_items
    }
    rows: list[dict[str, Any]] = []
    number = 1
    for category, names in (
        ("In", IN_ITEMS),
        ("Out", OUT_ITEMS),
        ("Loop", LOOP_ITEMS),
    ):
        for base_name in names:
            rows.append(proposal(number, category, base_name))
            number += 1

    seen: set[str] = set()
    collisions: list[dict[str, str]] = []
    for row in rows:
        key = row["nameKey"]
        if key in seen or key in existing:
            collisions.append(
                {
                    "proposalId": row["proposalId"],
                    "name": row["name"],
                    "nameKey": key,
                }
            )
        seen.add(key)
    if len(rows) != 100:
        raise RuntimeError(f"Expected 100 proposals, got {len(rows)}")
    if collisions:
        raise RuntimeError(f"Name collisions: {collisions}")

    categories = collections.Counter(row["category"] for row in rows)
    payload = {
        "schemaVersion": 1,
        "kind": "text-animation-proposals",
        "generatedAt": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "sourceManifest": str(args.manifest.resolve()),
        "existingAnimationCount": len(existing_items),
        "existingUniqueNameCount": len(existing),
        "proposalCount": len(rows),
        "categories": dict(sorted(categories.items())),
        "description": (
            "100 concept proposals validated against the existing text "
            "animation manifest. These are not runnable assets and contain no "
            "invented CapCut effectId/resourceId values."
        ),
        "importRule": (
            "Before promoting a proposal, capture or author a compatible "
            "CapCut effect package, register real effectId/resourceId, then "
            "append the runnable record to text-animations.json."
        ),
        "validation": {
            "nameCollisions": collisions,
            "uniqueNameKeys": len(seen),
            "validatedAgainstAnimationCount": len(existing_items),
            "validatedAgainstUniqueNameCount": len(existing),
        },
        "items": rows,
    }
    write_atomic(args.output, payload)
    print(
        f"PASS output={args.output} proposals={len(rows)} "
        f"in={categories['In']} out={categories['Out']} "
        f"loop={categories['Loop']} collisions={len(collisions)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
