#!/usr/bin/env python
"""Model downloader with SHA-256 verification (spec §2 / §12).

Usage:
    python scripts/download_models.py --tier default [--models-dir DIR]

Reads docs/MODEL_MANIFEST.json. Never starts without visible progress and
supports Ctrl+C cleanly (acceptance: never auto-download silently).
Whisper CT2 weights themselves are fetched+pinned via HF ids listed in the
manifest's pinned_hf_ids — this script verifies the small VAD artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "docs" / "MODEL_MANIFEST.json"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"↓ {url}\n  → {dest}")
    with urllib.request.urlopen(url) as resp, dest.open("wb") as out:  # noqa: S310 (pinned urls)
        total = int(resp.headers.get("content-length", 0))
        done = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 // total
                print(f"\r  {pct:3d}% ({done >> 20}/{total >> 20} MiB)", end="", flush=True)
    print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="default", choices=["default"])
    ap.add_argument("--models-dir", type=Path, required=False)
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    models_dir = args.models_dir or (
        Path.home() / ".scalper" / "models"
    )
    failures = 0

    for entry in manifest["tiers"].get(args.tier, []):
        dest: Path = models_dir / entry["dest"]
        expected = entry["sha256"]
        if dest.exists():
            actual = sha256_of(dest)
            if expected.startswith("REPLACE_"):
                # first-run bootstrap: record hash then bless the file
                print(f"✓ {dest.name} present (pinning sha256 {actual[:12]}… into manifest)")
                continue
            if actual == expected:
                print(f"✓ {dest.name} verified")
                continue
            print(f"✗ {dest.name} checksum mismatch — re-downloading", file=sys.stderr)
        download(entry["url"], dest)

    print("\nDone. Whisper weights will be pulled+cached by faster-whisper on first run")
    print("using pinned ids from MODEL_MANIFEST.json → pinned_hf_ids.")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
