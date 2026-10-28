"""Encode generated originals for web delivery without altering their composition.

Original PNGs stay in assets/weather/source. RGB delivery uses JPEG because
Streamlit's static-file allowlist serves JPEG/PNG with image content types.
"""
from pathlib import Path
import hashlib
import json

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / "assets" / "weather" / "source"
    target = ROOT / "static" / "weather"
    target.mkdir(parents=True, exist_ok=True)
    manifest = {"origin": "Built-in image generation; approved workbench reference", "assets": []}
    for path in sorted(source.glob("*.png")):
        with Image.open(path) as original:
            image = original.copy()
            edge = 192 if path.stem == "brand-cloud" else 1280
            image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
            alpha = image.mode == "RGBA"
            output = target / (path.stem + (".png" if alpha else ".jpg"))
            if alpha:
                image.save(output, optimize=True)
            else:
                image.convert("RGB").save(output, quality=90, optimize=True, progressive=True)
            manifest["assets"].append({
                "name": path.stem, "source": path.relative_to(ROOT).as_posix(),
                "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "file": output.relative_to(ROOT).as_posix(), "size": list(image.size),
                "bytes": output.stat().st_size,
                "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            })
    (ROOT / "assets/weather/manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Encoded {len(manifest['assets'])} assets; {sum(x['bytes'] for x in manifest['assets']):,} bytes")


if __name__ == "__main__":
    main()
