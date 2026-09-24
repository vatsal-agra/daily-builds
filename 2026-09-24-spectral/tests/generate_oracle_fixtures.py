"""Generates JPEG files + a manifest of our own decoder's pixel output,
for tests/browser_oracle_test.cjs to independently check against a real
browser's built-in JPEG decoder (Chromium via Playwright).

Usage: python3 tests/generate_oracle_fixtures.py <output_dir>
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spectral import testimages, encoder, decoder


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    specs = [
        ("gradient", testimages.gradient(65, 50)),
        ("checkerboard", testimages.checkerboard(33, 33, 4)),
        ("radial", testimages.radial_target(48, 48)),
        ("solid", testimages.solid(9, 9, (12, 200, 90))),
        ("photo", testimages.synthetic_photo(96, 96, seed=42)),
    ]
    manifest = []
    for name, img in specs:
        for quality in (15, 50, 85):
            for subsampling in ("444", "422", "420"):
                data = encoder.encode(img, quality=quality, subsampling=subsampling)
                fname = f"{name}_q{quality}_{subsampling}.jpg"
                path = os.path.join(out_dir, fname)
                with open(path, "wb") as f:
                    f.write(data)
                out = decoder.decode(data)
                manifest.append({
                    "file": fname,
                    "width": img.width,
                    "height": img.height,
                    "subsampling": subsampling,
                    "r": out.r, "g": out.g, "b": out.b,
                })
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f)
    print(f"wrote {len(manifest)} fixture JPEGs + manifest.json to {out_dir}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: generate_oracle_fixtures.py <output_dir>")
    main(sys.argv[1])
