"""Encode generated RGBA artwork as compact WebP assets without altering composition."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--partial", action="store_true", help="Encode only source images already available")
    args = parser.parse_args()
    directory = ROOT / "assets" / "landmarks"
    catalog = json.loads((directory / "catalog.json").read_text(encoding="utf-8"))
    output = ROOT / "static" / "weather" / "landmarks"
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    previous = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    cached = {record["id"]: record for record in previous.get("assets", [])}
    records, missing, encoded = [], [], 0
    for city in catalog["cities"]:
        source = directory / "source" / (city["id"] + ".png")
        if not source.is_file():
            missing.append(city["id"])
            continue
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        target = output / city["asset"]
        record = cached.get(city["id"])
        if (record and record.get("source_sha256") == source_hash and target.is_file()
                and record.get("sha256") == hashlib.sha256(target.read_bytes()).hexdigest()):
            records.append(record)
            continue
        with Image.open(source) as image:
            if image.mode != "RGBA" or image.getchannel("A").getextrema() != (0, 255):
                raise ValueError(f"Expected genuine transparent artwork: {source.name}")
            source_size = list(image.size)
            image.thumbnail((1024, 448), Image.Resampling.LANCZOS)
            image.save(target, "WEBP", quality=88, method=6)
            encoded += 1
            records.append({"id": city["id"], "city": city["city"], "landmark": city["landmark"],
                            "asset": str(target.relative_to(ROOT)).replace("\\", "/"),
                            "pixels": list(image.size), "source_pixels": source_size,
                            "source_sha256": source_hash,
                            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                            "bytes": target.stat().st_size})
    result = {"generation": "built-in image_gen", "source_count": len(records), "expected_count": len(catalog["cities"]),
              "optimization": "aspect-preserving downscale and WebP encoding only; original RGBA files retained locally",
              "missing": missing, "assets": records}
    manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"available": len(records), "encoded": encoded, "missing": missing,
                      "bytes": sum(r["bytes"] for r in records)}, ensure_ascii=False))
    if missing and not args.partial:
        raise SystemExit("Landmark library incomplete")


if __name__ == "__main__":
    main()
