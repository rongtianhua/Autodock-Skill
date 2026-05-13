#!/usr/bin/env python3
"""Download P2Rank model files (excluded from git due to size > 50 MB).

Usage:
    python download_models.py        # Download all models
    python download_models.py --list # List available models
"""
import os
import sys
import argparse
import urllib.request
from pathlib import Path

BASE_URL = "https://github.com/rdk/p2rank/releases/download/2.5.1"
MODELS = {
    "default": "models/default/model.zst",
    "alphafold": "models/alphafold/model.zst",
    "rescore_conservation": "models/rescore_conservation/model.zst",
    "rescore_2024": "models/rescore_2024/model.zst",
    "conservation_hmm": "models/conservation_hmm/model.zst",
    "alphafold_conservation_hmm": "models/alphafold_conservation_hmm/model.zst",
    "default_rescore": "models/default_rescore/model.zst",
}


def download_file(url: str, dest: Path, chunk_size: int = 8192) -> None:
    """Download with progress bar."""
    if dest.exists():
        print(f"  ✓ Already exists: {dest}")
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  → Downloading {dest.name} ...", end=" ", flush=True)

    try:
        urllib.request.urlretrieve(url, str(dest))
        size_mb = dest.stat().st_size / (1024 * 1024)
        print(f"done ({size_mb:.1f} MB)")
    except Exception as e:
        print(f"FAILED: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description="Download P2Rank model files")
    parser.add_argument("--list", action="store_true", help="List available models")
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    models_dir = script_dir / "models"

    if args.list:
        print("Available P2Rank models:")
        for name, path in MODELS.items():
            dest = models_dir / path
            status = "✓ downloaded" if dest.exists() else "✗ missing"
            print(f"  {name:30s} {status}")
        return

    print("Downloading P2Rank models ...")
    print(f"Destination: {models_dir}")
    print()

    for name, path in MODELS.items():
        url = f"{BASE_URL}/{Path(path).name}"
        dest = models_dir / path
        download_file(url, dest)

    print()
    print("All models downloaded successfully.")


if __name__ == "__main__":
    main()
